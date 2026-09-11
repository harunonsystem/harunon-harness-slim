"""Immutable distribution plans and stateful apply orchestration.

The resolver remains the source of manifest truth.  This module owns the
inspect -> plan -> apply lifecycle so callers can inspect a stable snapshot
without coupling tests to CLI output or filesystem mutation details.

配布先（destination）への観測と書き込みはすべて FileSystem adapter を通す。
本番は PathFileSystem、テストは record/in-memory adapter を注入する。SSOT 側
（repo）の読み取りは resolver / settings_sync が host Path で行う（manifest の
解決は adapter 化していないため、両者を揃えて host 読みにする）。
"""
from __future__ import annotations

import contextlib
import datetime as _datetime
import fcntl
import hashlib
import json
import os
import subprocess
import stat
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Protocol, Sequence

from . import settings_sync
from .config import load_target
from .merge import merge_overlay_into_settings
from .paths import relative_name
from .settings_sync import SettingsChange
from .unmanaged_skills import allowlisted_skill_names
from .resolver import (
    CURATED_SKILLS_SOURCE,
    Drift,
    find_spec_for_path,
    in_uninitialized_submodule,
    lacks_exec_bit,
    manifest,
    requires_executable,
    resolve_pull_source,
    uninitialized_submodule_paths,
)

LEDGER_FILENAME = ".harness-distributed.json"
LEDGER_SCHEMA_VERSION = 1
# target 改名時の旧名。ledger の "target" が旧名でも読めるようにし、次の --push で
# 新名に書き直す（改名直後の全マシンで初回 bootstrap が止まらないための互換層）
LEDGER_TARGET_ALIASES: dict[str, tuple[str, ...]] = {"shared-agents": ("portable",)}
# backups/ 配下に保持する backup ディレクトリの最大数（古いものから削除）
BACKUP_KEEP = 5


# ---------------------------------------------------------------------------
# Filesystem seam

@dataclass(frozen=True)
class Observation:
    """Immutable observation of one filesystem path."""

    path: str
    exists: bool
    is_file: bool
    is_symlink: bool
    digest: str | None
    mode: int | None
    link_target: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> "Observation":
        is_link = path.is_symlink()
        exists = path.exists() or is_link
        if not exists:
            return cls(path.as_posix(), False, False, is_link, None, None, None)
        try:
            # ``stat`` follows a symlink, matching the executable-bit check
            # (what actually runs is the link target).  ``is_symlink`` and
            # ``link_target`` let callers avoid chmod-ing through a live link.
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            mode = None
        digest: str | None = None
        is_file = path.is_file()
        if is_file and not is_link:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = None
        link_target: str | None = None
        if is_link:
            try:
                link_target = os.readlink(path)
            except OSError:
                link_target = None
        return cls(path.as_posix(), True, is_file, is_link, digest, mode, link_target)


class FileSystem(Protocol):
    """配布先を観測・変更するための seam。

    本番は :class:`PathFileSystem`。テストは決定的な adapter を注入して
    plan / apply をホスト I/O なしで検証する。全メソッドを実装すること。
    """

    def observe(self, path: Path) -> Observation: ...

    def resolve(self, path: Path) -> Path: ...

    def read_bytes(self, path: Path) -> bytes: ...

    def write_bytes(self, path: Path, content: bytes) -> None: ...

    def atomic_write(self, path: Path, content: bytes) -> None: ...

    def mkdir(self, path: Path) -> None: ...

    def is_dir(self, path: Path) -> bool: ...

    def iterdir(self, path: Path) -> Sequence[Path]: ...

    def rename(self, source: Path, destination: Path) -> None: ...

    def copy(self, source: Path, destination: Path) -> None: ...

    def remove(self, path: Path) -> None: ...

    def remove_tree(self, path: Path) -> None: ...

    def chmod(self, path: Path, mode: int) -> None: ...

    def lock(self, destination: Path) -> contextlib.AbstractContextManager: ...


class PathFileSystem:
    """Production filesystem adapter."""

    @staticmethod
    def _ensure_parent(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def observe(self, path: Path) -> Observation:
        return Observation.from_path(path)

    def resolve(self, path: Path) -> Path:
        return path.resolve()

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes(self, path: Path, content: bytes) -> None:
        self._ensure_parent(path)
        path.write_bytes(content)

    def mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def iterdir(self, path: Path) -> Sequence[Path]:
        return tuple(path.iterdir())

    def rename(self, source: Path, destination: Path) -> None:
        self._ensure_parent(destination)
        os.replace(source, destination)

    def copy(self, source: Path, destination: Path) -> None:
        """Copy a backup without dereferencing symlinks."""
        self._ensure_parent(destination)
        shutil.copy2(source, destination, follow_symlinks=False)

    def remove(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()

    def remove_tree(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    def chmod(self, path: Path, mode: int) -> None:
        path.chmod(mode)

    def atomic_write(self, path: Path, content: bytes) -> None:
        """Write via a sibling temp file and ``os.replace``.

        mkstemp creates the temp file 0600; an existing destination keeps its
        mode (hooks distributed as 0755 must not silently become 0600).
        """
        self._ensure_parent(path)
        existing_mode: int | None = None
        with contextlib.suppress(OSError):
            existing_mode = stat.S_IMODE(path.stat().st_mode)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if existing_mode is not None:
                os.chmod(temp_name, existing_mode)
            os.replace(temp_name, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise

    @contextlib.contextmanager
    def lock(self, destination: Path) -> Iterator[None]:
        """Serialize mutations for one destination with a sibling flock file."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock_path = destination.parent / f".{destination.name}.harness-distribution.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()


class _LiveReader:
    """settings_sync.LiveReader を FileSystem adapter で実装する。"""

    def __init__(self, fs: FileSystem) -> None:
        self._fs = fs

    def is_file(self, path: Path) -> bool:
        return self._fs.observe(path).is_file

    def read_text(self, path: Path) -> str:
        return self._fs.read_bytes(path).decode("utf-8")


# ---------------------------------------------------------------------------
# Plan data

class ApplyStatus(str, Enum):
    """Terminal state of an apply operation."""

    APPLIED = "APPLIED"
    DRY_RUN = "DRY_RUN"
    STALE = "STALE"
    INVALID = "INVALID"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"


class OperationStatus(str, Enum):
    """State of one operation event in an apply result."""

    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Operation:
    """One planned mutation, including the payload needed to replay it."""

    kind: str
    path: str
    status: OperationStatus = OperationStatus.PLANNED
    payload: bytes | None = None
    backup_path: str | None = None
    mode: int | None = None
    reason: str | None = None
    source_path: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    change: SettingsChange | None = None
    # cleanup-backups: 削除する destination 相対パス
    paths: tuple[str, ...] = ()
    # push サマリの表示バケツ（renderer が kind/metadata から再推測しないよう構築時に確定させる）
    bucket: str | None = None
    # backup: settings 系の退避は dry-run 行を出さない（renderer が phase を読み直さない）
    skip_dry_run_line: bool = False

    @property
    def payload_digest(self) -> str | None:
        if self.payload is None:
            return None
        return hashlib.sha256(self.payload).hexdigest()

    @property
    def metadata_map(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.metadata))


@dataclass(frozen=True)
class PlanSummary:
    """push / pull の集計。renderer が文字列を再パースせず読むための typed view。"""

    unchanged_count: int = 0
    modified_stale_paths: tuple[str, ...] = ()
    pruned_backups: tuple[str, ...] = ()
    disabled_plugin_files: tuple[str, ...] = ()
    ledger_entries: int = 0
    manifest_entries: int = 0


@dataclass(frozen=True)
class DistributionInspection:
    """Read-only state used to construct a distribution plan."""

    operation: str
    target: str
    repo_root: str
    destination: str
    manifest_files: tuple[tuple[str, bytes], ...]
    warnings: tuple[str, ...]
    drifts: tuple[Drift, ...]
    ledger: tuple[tuple[str, str], ...]
    obsolete_files: tuple[str, ...]
    incomplete_destinations: tuple[str, ...]
    disabled_plugin_files: tuple[str, ...]
    observations: tuple[Observation, ...]
    config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def files(self) -> Mapping[str, bytes]:
        return MappingProxyType(dict(self.manifest_files))

    @property
    def has_drift(self) -> bool:
        return bool(self.drifts)

    @property
    def destination_exists(self) -> bool:
        """observations[0] は常に destination 自体の観測。"""
        return self.observations[0].exists


@dataclass(frozen=True)
class DistributionPlan:
    """Immutable operation payload and observed destination snapshot."""

    operation: str
    target: str
    repo_root: str
    destination: str
    dry_run: bool
    prune: bool
    identity: str
    snapshot: tuple[Observation, ...]
    operations: tuple[Operation, ...]
    backup_base: str | None = None
    warnings: tuple[str, ...] = ()
    summary: PlanSummary = PlanSummary()

    @property
    def destination_path(self) -> Path:
        return Path(self.destination)

    @property
    def repo_path(self) -> Path:
        return Path(self.repo_root)


@dataclass(frozen=True)
class ApplyEvent:
    """Structured operation event; CLI renderers may format it freely."""

    index: int
    kind: str
    path: str
    status: OperationStatus
    reason: str | None = None
    backup_path: str | None = None


@dataclass(frozen=True)
class ApplyResult:
    """Structured result of applying one immutable plan."""

    status: ApplyStatus
    plan_identity: str
    events: tuple[ApplyEvent, ...] = ()
    error: str | None = None
    applied_count: int = 0
    failed_count: int = 0
    exit_code: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


# ---------------------------------------------------------------------------
# Generic helpers

def _resolve_destination(cfg: Mapping[str, Any], override: Path | None) -> Path:
    """配布先を 1 箇所で決める（CLI の --dir が無ければ target の configDir）。"""
    return Path(cfg["configDir"]) if override is None else Path(override)


def _in_incomplete_destination(rel: str, incomplete_dests: set[str]) -> bool:
    return any(rel.startswith(destination) for destination in incomplete_dests)


def _obsolete_files(cfg: Mapping[str, Any]) -> list[str]:
    """Return safe exact relative tombstones declared by a target."""
    return [
        Path(relative_name(value, "obsoleteFiles")).as_posix()
        for value in cfg.get("obsoleteFiles", [])
    ]


def _source_is_git_ignored(repo: Path, rel: str) -> bool:
    """dest 相対パス rel に対応する source（core / extras）が git 無視対象なら True。

    live 側の config.yml（skill-override の symlink 等）は source 側で gitignore
    される「意図的なローカル専用ファイル」であり、prune で消してはならない。
    git 不在時は False（安全側で判定を続行）。
    """
    candidates = [
        repo / "packages" / "core" / rel,
        repo / "packages" / "extras" / "_active" / rel,
    ]
    for path in candidates:
        try:
            result = subprocess.run(
                ["git", "check-ignore", "-q", str(path)],
                cwd=repo,
                capture_output=True,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode == 0:
            return True
    return False


def _walk_files(fs: FileSystem, root: Path) -> tuple[Path, ...]:
    """Recursively list files through the adapter for deterministic snapshots."""
    observed = fs.observe(root)
    if not observed.exists:
        return ()
    if observed.is_symlink or observed.is_file:
        return (root,)
    result: list[Path] = []
    for child in sorted(fs.iterdir(root), key=lambda item: item.as_posix()):
        child_observed = fs.observe(child)
        if not child_observed.exists:
            continue
        if child_observed.is_symlink or child_observed.is_file:
            result.append(child)
        else:
            result.extend(_walk_files(fs, child))
    return tuple(result)


def _remove_empty_dirs(fs: FileSystem, start: Path, stop: Path) -> None:
    """Remove empty real directories below ``stop`` through the adapter."""
    current = start
    while current != stop:
        observed = fs.observe(current)
        if not fs.is_dir(current) or observed.is_symlink:
            return
        if fs.iterdir(current):
            return
        fs.remove(current)
        current = current.parent


def _manifest_drifts(
    destination: Path,
    cfg: Mapping[str, Any],
    resolved: Any,
    fs: FileSystem,
) -> list[Drift]:
    """manifest と destination を比較する。

    - missing: manifest にあるが live に存在しない
    - changed: 内容が異なる（symlink・ディレクトリなどファイルでないものも含む）
    - mode: 内容は一致するが実行ビットを欠く（symlink の参照先が非実行の場合も含む）
    - live にだけあるファイルは対象外（unmanaged 検出は別責務）
    """
    drifts: list[Drift] = []
    for rel, expected in resolved.files.items():
        path = destination / rel
        observed = fs.observe(path)
        if not observed.exists:
            drifts.append(Drift(path=rel, kind="missing"))
        elif not observed.is_file or fs.read_bytes(path) != expected:
            drifts.append(Drift(path=rel, kind="changed"))
        elif requires_executable(rel, dict(cfg)) and lacks_exec_bit(observed.mode):
            drifts.append(Drift(path=rel, kind="mode"))
    return drifts


def _read_ledger(fs: FileSystem, destination: Path, target: str) -> dict[str, str] | None:
    """Read the target-bound manifest ledger; malformed state fails closed."""
    path = destination / LEDGER_FILENAME
    if not fs.observe(path).is_file:
        return None
    try:
        data = json.loads(fs.read_bytes(path).decode("utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
        raise ValueError(f"invalid distribution ledger: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("invalid distribution ledger: root must be an object")
    if data.get("schemaVersion") != LEDGER_SCHEMA_VERSION:
        raise ValueError("unsupported distribution ledger schemaVersion")
    accepted_targets = (target, *LEDGER_TARGET_ALIASES.get(target, ()))
    if data.get("target") not in accepted_targets:
        raise ValueError(f"distribution ledger target mismatch: {data.get('target')!r} != {target!r}")
    files = data.get("files")
    if not isinstance(files, dict):
        raise ValueError("distribution ledger files must be an object")
    result: dict[str, str] = {}
    for raw_path, digest in files.items():
        rel = Path(relative_name(raw_path, "distribution ledger")).as_posix()
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"invalid distribution ledger digest: {raw_path!r}")
        try:
            int(digest, 16)
        except ValueError as error:
            raise ValueError(f"invalid distribution ledger digest: {raw_path!r}") from error
        result[rel] = digest
    return result


def _is_allowlisted_skill(rel: str, allowlisted: frozenset[str]) -> bool:
    """dest 相対パスが allowlist 宣言済み skill の配下か。

    allowlist は skill 名の宣言なので skills/ 配下にだけ効かせる（rules/ 等に同名の
    ファイルがあっても保護対象にしない）。
    """
    parts = Path(rel).parts
    return len(parts) >= 2 and parts[0] == "skills" and parts[1] in allowlisted


def _plan_ledger_cleanup(
    ledger: dict[str, str] | None,
    manifest_files: Mapping[str, bytes],
    incomplete_dests: set[str],
    destination: Path,
    fs: FileSystem,
    allowlisted: frozenset[str] = frozenset(),
) -> tuple[list[str], dict[str, str], list[str]]:
    """Plan safe stale removal and retain modified/incomplete entries for later pushes."""
    if ledger is None:
        return [], {}, []
    removable: list[str] = []
    pending: dict[str, str] = {}
    modified: list[str] = []
    root = fs.resolve(destination)
    for rel, previous_digest in sorted(ledger.items()):
        if rel in manifest_files:
            continue
        # 過去に harness 管理だった skill が allowlist 宣言（= 所有が installer に移った）
        # に変わった場合、台帳経由の remove-managed で消えてしまう。prune 側のフィルタは
        # この経路より後なので間に合わない。台帳からは外し、実体は残す。
        if _is_allowlisted_skill(rel, allowlisted):
            continue
        if _in_incomplete_destination(rel, incomplete_dests):
            pending[rel] = previous_digest
            continue
        path = destination / rel
        observed = fs.observe(path)
        if not observed.exists and not observed.is_symlink:
            continue
        if observed.is_symlink:
            pending[rel] = previous_digest
            modified.append(rel)
            continue
        # A managed file reached through an intermediate symlinked directory
        # must not be treated as safely removable.
        try:
            fs.resolve(path).relative_to(root)
        except ValueError as error:
            raise ValueError(f"distribution ledger path escapes through symlink: {rel}") from error
        if not observed.is_file or hashlib.sha256(fs.read_bytes(path)).hexdigest() != previous_digest:
            pending[rel] = previous_digest
            modified.append(rel)
            continue
        removable.append(rel)
    return removable, pending, modified


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _plan_identity(plan_data: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(plan_data)).hexdigest()


def _observation_key(observation: Observation) -> tuple[Any, ...]:
    return (
        observation.path,
        observation.exists,
        observation.is_file,
        observation.is_symlink,
        observation.digest,
        observation.mode,
        observation.link_target,
    )


def _snapshot_matches(plan: DistributionPlan, fs: FileSystem) -> bool:
    for expected in plan.snapshot:
        current = fs.observe(Path(expected.path))
        if _observation_key(current) != _observation_key(expected):
            return False
    return True


def _operation_data(operation: Operation) -> dict[str, Any]:
    return {
        "kind": operation.kind,
        "path": operation.path,
        "payload": operation.payload_digest,
        "backupPath": operation.backup_path,
        "mode": operation.mode,
        "reason": operation.reason,
        "sourcePath": operation.source_path,
        "metadata": dict(operation.metadata),
        "change": (
            None if operation.change is None
            else [operation.change.label, list(operation.change.changed), list(operation.change.removed)]
        ),
        "paths": list(operation.paths),
    }


def _manifest_tuple(resolved: Any) -> tuple[tuple[str, bytes], ...]:
    return tuple(sorted(resolved.files.items()))


# ---------------------------------------------------------------------------
# inspect

def _inspection_drifts(
    repo: Path,
    destination: Path,
    cfg: dict[str, Any],
    resolved: Any,
    ledger: dict[str, str] | None,
    fs: FileSystem,
) -> list[Drift]:
    """Compute all user-visible drift kinds without mutating state."""

    drifts = _manifest_drifts(destination, cfg, resolved, fs)
    _, _, modified_stale = _plan_ledger_cleanup(
        ledger,
        resolved.files,
        resolved.incomplete_dests,
        destination,
        fs,
        allowlisted_skill_names(repo),
    )
    obsolete_files = _obsolete_files(cfg)
    obsolete_set = set(obsolete_files)
    if ledger is not None:
        for rel in sorted(set(ledger) - set(resolved.files)):
            if _in_incomplete_destination(rel, resolved.incomplete_dests):
                continue
            if rel in obsolete_set:
                continue
            observed = fs.observe(destination / rel)
            if observed.exists or observed.is_symlink:
                kind = "modified-stale" if rel in modified_stale else "stale-managed"
                drifts.append(Drift(path=rel, kind=kind))
    drifts.extend(settings_sync.drifts(cfg, repo, destination, _LiveReader(fs)))
    for rel in obsolete_files:
        if fs.observe(destination / rel).is_file:
            drifts.append(Drift(path=rel, kind="obsolete"))
    return drifts


def _snapshot_paths(
    destination: Path,
    manifest_files: Mapping[str, bytes],
    obsolete_files: Sequence[str],
    ledger: Mapping[str, str] | None,
    fs: FileSystem,
) -> tuple[Observation, ...]:
    paths = set(manifest_files) | set(obsolete_files)
    if ledger is not None:
        paths.update(ledger)
    paths.add(LEDGER_FILENAME)
    return tuple(fs.observe(destination / rel) for rel in sorted(paths))


def inspect(
    target: str,
    repo: Path,
    live_dir: Path | None,
    *,
    fs: FileSystem,
) -> DistributionInspection:
    """Inspect destination state; never writes or repairs files."""

    repo = Path(repo)
    cfg = load_target(target, repo)
    destination = _resolve_destination(cfg, live_dir)
    resolved = manifest(target, repo, cfg=cfg)
    ledger = _read_ledger(fs, destination, target)
    obsolete_files = tuple(_obsolete_files(cfg))
    destination_observation = fs.observe(destination)
    if not destination_observation.exists:
        # Keep the missing destination in the immutable inspection itself so the
        # renderer never probes the host filesystem behind the adapter's back.
        drifts = [Drift(path=destination.as_posix(), kind="missing")]
        observations = (destination_observation,)
    else:
        drifts = _inspection_drifts(repo, destination, cfg, resolved, ledger, fs)
        observations = (
            destination_observation,
            *_snapshot_paths(destination, resolved.files, obsolete_files, ledger, fs),
        )
    return DistributionInspection(
        operation="inspect",
        target=target,
        repo_root=repo.as_posix(),
        destination=destination.as_posix(),
        manifest_files=_manifest_tuple(resolved),
        warnings=tuple(resolved.warnings),
        drifts=tuple(drifts),
        ledger=tuple(sorted((ledger or {}).items())),
        obsolete_files=obsolete_files,
        incomplete_destinations=tuple(sorted(resolved.incomplete_dests)),
        disabled_plugin_files=tuple(sorted(resolved.disabled_plugin_files)),
        observations=observations,
        config=MappingProxyType(dict(cfg)),
    )


# ---------------------------------------------------------------------------
# push planning

def _prune_candidates(
    cfg: Mapping[str, Any],
    resolved: Any,
    destination: Path,
    repo: Path,
    fs: FileSystem,
) -> list[str]:
    allowlisted = allowlisted_skill_names(repo)
    candidates: list[str] = []
    for dest_key in cfg.get("distribute", {}):
        if not dest_key.endswith("/") or dest_key in resolved.incomplete_dests:
            continue
        base = destination / dest_key
        if not fs.is_dir(base):
            continue
        for child in _walk_files(fs, base):
            observed = fs.observe(child)
            if observed.is_symlink or not observed.is_file or child.name == ".DS_Store":
                continue
            rel = child.relative_to(destination).as_posix()
            rel_in_base = child.relative_to(base)
            if any(part.startswith(".") for part in rel_in_base.parts):
                continue
            # allowlist は skill 名の宣言なので skills/ 宛てにだけ効かせる
            # （rules/ 等に同名のファイルがあっても保護対象にしない）。
            if dest_key == "skills/" and rel_in_base.parts[0] in allowlisted:
                continue
            if rel in resolved.files or _source_is_git_ignored(repo, rel):
                continue
            candidates.append(rel)
    return candidates


def _backup_name(base: Path, rel: str, used: set[str], fs: FileSystem) -> Path:
    candidate = base / rel
    stem = candidate.stem
    suffix = candidate.suffix
    number = 0
    while candidate.as_posix() in used or fs.observe(candidate).exists:
        number += 1
        candidate = candidate.with_name(f"{stem}-{number}{suffix}")
    used.add(candidate.as_posix())
    return candidate


def _backup_base(destination: Path, fs: FileSystem) -> Path:
    timestamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = destination / "backups" / f"bootstrap-{timestamp}"
    suffix = 0
    while fs.observe(base).exists:
        suffix += 1
        base = destination / "backups" / f"bootstrap-{timestamp}-{suffix}"
    return base


class BackupPlanner:
    """1 push 分の backup operation を所有する。

    同じ destination 相対パスは 1 回だけ退避する（manifest と settings が同じ
    configFile を触るときに二重 backup しない）。backup 先の名前衝突は連番で避ける。
    """

    def __init__(self, destination: Path, base: Path, fs: FileSystem) -> None:
        self._destination = destination
        self._base = base
        self._fs = fs
        self._planned: set[str] = set()
        self._used_names: set[str] = set()
        self.operations: list[Operation] = []

    def add(self, rel: str, *, phase: str = "backup") -> None:
        if rel in self._planned:
            return
        observed = self._fs.observe(self._destination / rel)
        if not (observed.exists or observed.is_symlink):
            return
        self._planned.add(rel)
        self.operations.append(Operation(
            kind="backup",
            path=rel,
            backup_path=_backup_name(self._base, rel, self._used_names, self._fs).as_posix(),
            metadata=(("phase", phase), ("strategy", "copy")),
            skip_dry_run_line=phase == "settings",
        ))

    @property
    def creates_backup(self) -> bool:
        return bool(self.operations)


# push サマリのバケツ名（distribute.py の renderer が kind から再推測せず読む）
_KIND_BUCKET = {
    "add": "added",
    "overwrite": "updated",
    "mode-symlink": "mode_unfixable",
    "remove-obsolete": "removed_obsolete",
    "remove-managed": "removed_managed",
    "prune": "pruned",
}


def _chmod_op(rel: str, *, count_mode: bool = False) -> Operation:
    return Operation(
        kind="chmod",
        path=rel,
        mode=0o755,
        metadata=(("phase", "manifest"),),
        bucket="mode_fixed" if count_mode else None,
    )


def _write_op(kind: str, rel: str, payload: bytes) -> Operation:
    return Operation(
        kind=kind, path=rel, payload=payload, source_path=rel,
        metadata=(("phase", "manifest"),), bucket=_KIND_BUCKET.get(kind),
    )


def _manifest_operations(
    cfg: Mapping[str, Any],
    resolved: Any,
    destination: Path,
    fs: FileSystem,
    backups: BackupPlanner,
) -> list[Operation]:
    """manifest の各ファイルについて add / overwrite / chmod を計画する。"""
    operations: list[Operation] = []
    for rel, payload in sorted(resolved.files.items()):
        path = destination / rel
        observed = fs.observe(path)
        executable = requires_executable(rel, cfg)
        if observed.is_symlink:
            # A content-identical symlink is intentionally left in place.  The
            # push contract reports an executable-bit mismatch without
            # chmod-ing through the link into the SSOT source.
            if observed.is_file and fs.read_bytes(path) == payload:
                if executable and lacks_exec_bit(observed.mode):
                    operations.append(Operation(
                        kind="mode-symlink", path=rel, reason="symlink", metadata=(("phase", "manifest"),),
                        bucket=_KIND_BUCKET["mode-symlink"],
                    ))
                continue
            backups.add(rel)
            operations.append(_write_op("overwrite", rel, payload))
            if executable and lacks_exec_bit(observed.mode):
                operations.append(_chmod_op(rel))
        elif not observed.exists:
            operations.append(_write_op("add", rel, payload))
            if executable:
                operations.append(_chmod_op(rel))
        elif not observed.is_file:
            raise ValueError(f"manifest destination is not a file: {rel}")
        elif fs.read_bytes(path) != payload:
            backups.add(rel)
            operations.append(_write_op("overwrite", rel, payload))
            if executable:
                operations.append(_chmod_op(rel))
        elif executable and lacks_exec_bit(observed.mode):
            operations.append(_chmod_op(rel, count_mode=True))
    return operations


def _cleanup_operations(
    cfg: Mapping[str, Any],
    resolved: Any,
    destination: Path,
    repo: Path,
    obsolete_files: Sequence[str],
    ledger_removals: Sequence[str],
    prune: bool,
    fs: FileSystem,
    backups: BackupPlanner,
) -> list[Operation]:
    """obsoleteFiles / ledger stale / prune の削除を計画する（退避付き）。"""
    operations: list[Operation] = []
    for rel in obsolete_files:
        observed = fs.observe(destination / rel)
        if observed.is_file and not observed.is_symlink:
            backups.add(rel)
            operations.append(Operation(
                kind="remove-obsolete", path=rel, metadata=(("phase", "cleanup"),),
                bucket=_KIND_BUCKET["remove-obsolete"],
            ))
    for rel in sorted(ledger_removals):
        observed = fs.observe(destination / rel)
        if observed.exists or observed.is_symlink:
            backups.add(rel)
            operations.append(Operation(
                kind="remove-managed", path=rel, metadata=(("phase", "cleanup"),),
                bucket=_KIND_BUCKET["remove-managed"],
            ))
    if prune:
        for rel in _prune_candidates(cfg, resolved, destination, repo, fs):
            backups.add(rel)
            base = next(
                (key.rstrip("/") for key in cfg.get("distribute", {})
                 if key.endswith("/") and rel.startswith(key)),
                "",
            )
            operations.append(Operation(
                kind="prune", path=rel, metadata=(("phase", "cleanup"), ("base", base)),
                bucket=_KIND_BUCKET["prune"],
            ))
    return operations


def _settings_update_operation(
    kind: str,
    config_file: str,
    payload: str,
    source: str,
    change: SettingsChange,
) -> Operation:
    return Operation(
        kind=kind,
        path=config_file,
        payload=payload.encode("utf-8"),
        source_path=source,
        change=change,
        metadata=(("phase", "settings"), ("label", change.label)),
    )


def _plan_settings_document(
    cfg: Mapping[str, Any],
    repo: Path,
    destination: Path,
    dry_run: bool,
    fs: FileSystem,
    backups: BackupPlanner,
) -> tuple[list[Operation], str | None, str | None]:
    """settingsSync.compose の段を operation に写す。合成順序はここでは決めない。

    Returns: (operations, config_file, 合成後のテキスト or None)
    None は「configFile は存在せず dry-run なので seed も overlay も走らない」状態。
    """
    composed = settings_sync.compose(dict(cfg), repo, destination, _LiveReader(fs))
    if composed is None:
        return [], None, None
    config_file = composed.config_file
    operations: list[Operation] = []
    for step in composed.steps:
        if step.kind == "settings-template":
            operations.append(Operation(
                kind="settings-template",
                path=config_file,
                payload=step.text.encode("utf-8"),
                source_path=step.source_rel,
                metadata=(("phase", "settings"),),
            ))
            if dry_run:
                # A dry-run does not create the template, so overlays have nothing
                # to sync against.
                return operations, config_file, None
            continue
        if not composed.seeded:
            backups.add(config_file, phase="settings")
        operations.append(_settings_update_operation(
            step.kind, config_file, step.text, step.source_rel, step.change,
        ))
    return operations, config_file, composed.text


def _extras_overlay_operations(
    cfg: Mapping[str, Any],
    repo: Path,
    destination: Path,
    config_file: str | None,
    config_text: str | None,
    fs: FileSystem,
    backups: BackupPlanner,
) -> list[Operation]:
    """extras の env.json / settings-overlay.json を destination/settings.json へ重ねる。

    extrasOverlay は settingsSync の configFile 名に関係なく settings.json を対象に
    する。両者が同じファイルなら settingsSync で合成済みのテキストを引き継ぐ。
    """
    if not cfg.get("extrasOverlay"):
        return []
    if config_file == "settings.json":
        text = config_text
    else:
        settings_path = destination / "settings.json"
        text = fs.read_bytes(settings_path).decode("utf-8") if fs.observe(settings_path).is_file else None
    if text is None:
        return []
    operations: list[Operation] = []
    settings = json.loads(text)
    for extra_name, overlay_name, overlay in settings_sync.extras_overlay_sources(dict(cfg), repo):
        merge_overlay_into_settings(settings, overlay, overlay_name)
        text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
        backups.add("settings.json")
        operations.append(Operation(
            kind="extras-overlay",
            path="settings.json",
            payload=text.encode("utf-8"),
            source_path=(repo / "packages" / "extras" / extra_name / overlay_name).as_posix(),
            metadata=(("phase", "extras"), ("extra", extra_name), ("overlay", overlay_name)),
        ))
    return operations


def _backup_rotation(destination: Path, creates_backup: bool, fs: FileSystem) -> list[str]:
    """backups/bootstrap-* を BACKUP_KEEP 世代に間引く対象（destination 相対）を返す。"""
    backup_root = destination / "backups"
    if not fs.is_dir(backup_root):
        return []
    existing = sorted(
        path for path in fs.iterdir(backup_root)
        if path.name.startswith("bootstrap-") and fs.is_dir(path)
    )
    # The current push creates one new backup directory when any backup
    # operation is planned; retain one fewer existing directory in that case.
    retain = max(BACKUP_KEEP - int(creates_backup), 0)
    doomed = existing[:-retain] if retain else existing
    return [path.relative_to(destination).as_posix() for path in doomed]


_PHASE_ORDER = {
    "backup": 0,
    "manifest": 2,
    "settings": 4,
    "extras": 6,
    "cleanup": 7,
    "ledger": 8,
}


def _operation_rank(operation: Operation) -> int:
    """replay 順: 退避 → manifest 内容 → mode → settings → extras → 削除 → ledger。"""
    phase = operation.metadata_map.get("phase", "")
    if operation.kind == "backup":
        return 0 if phase == "backup" else 1
    if operation.kind in {"chmod", "mode-symlink"}:
        return 3
    if operation.kind == "settings-template":
        return 4
    if operation.kind in {"settings-sync", "settings-overlay"}:
        return 5
    if operation.kind == "cleanup-backups":
        return 9
    return _PHASE_ORDER[phase]


def _order_operations(operations: Sequence[Operation]) -> tuple[Operation, ...]:
    return tuple(sorted(operations, key=_operation_rank))


def _snapshot_for(
    destination: Path,
    repo: Path,
    operations: Sequence[Operation],
    destination_rels: set[str],
    fs: FileSystem,
) -> tuple[Observation, ...]:
    """apply 時に「plan 後に destination が変わっていない」ことを判定する観測集合。"""
    rels = set(destination_rels)
    source_paths: set[Path] = set()
    for operation in operations:
        if operation.kind not in {"warning", "pull-skip", "cleanup-backups"}:
            if operation.source_path:
                source_paths.add(repo / operation.source_path)
            else:
                rels.add(operation.path)
        if operation.backup_path:
            backup_path = Path(operation.backup_path)
            try:
                rels.add(backup_path.relative_to(destination).as_posix())
            except ValueError:
                source_paths.add(backup_path)
        rels.update(operation.paths)
    return tuple(
        [fs.observe(destination)]
        + [fs.observe(destination / rel) for rel in sorted(rels)]
        + [fs.observe(path) for path in sorted(source_paths, key=lambda item: item.as_posix())]
    )


def plan_push(
    target: str,
    repo: Path,
    dest_dir: Path | None,
    dry_run: bool,
    prune: bool,
    *,
    fs: FileSystem,
) -> DistributionPlan:
    """Resolve a complete push payload and freeze destination observations."""
    repo = Path(repo)
    cfg = load_target(target, repo)
    destination = _resolve_destination(cfg, dest_dir)
    resolved = manifest(target, repo, cfg=cfg)
    obsolete_files = tuple(sorted(_obsolete_files(cfg)))
    overlap = sorted(set(obsolete_files) & set(resolved.files))
    if overlap:
        raise ValueError(f"obsoleteFiles overlaps manifest: {', '.join(overlap)}")
    ledger = _read_ledger(fs, destination, target)
    ledger_removals, ledger_pending, modified_stale = _plan_ledger_cleanup(
        ledger,
        resolved.files,
        resolved.incomplete_dests,
        destination,
        fs,
        allowlisted_skill_names(repo),
    )
    excluded = set(obsolete_files) | set(modified_stale)
    ledger_removals = [rel for rel in ledger_removals if rel not in excluded]

    backup_base = _backup_base(destination, fs)
    backups = BackupPlanner(destination, backup_base, fs)
    operations: list[Operation] = []
    operations += _manifest_operations(cfg, resolved, destination, fs, backups)
    operations += _cleanup_operations(
        cfg, resolved, destination, repo, obsolete_files, ledger_removals, prune, fs, backups,
    )
    settings_ops, config_file, config_text = _plan_settings_document(
        cfg, repo, destination, dry_run, fs, backups,
    )
    operations += settings_ops
    operations += _extras_overlay_operations(cfg, repo, destination, config_file, config_text, fs, backups)
    old_backup_paths = _backup_rotation(destination, backups.creates_backup, fs)

    ledger_files = {rel: hashlib.sha256(content).hexdigest() for rel, content in resolved.files.items()}
    ledger_files.update({
        rel: digest
        for rel, digest in ledger_pending.items()
        if fs.observe(destination / rel).exists or fs.observe(destination / rel).is_symlink
    })
    ledger_payload = _canonical_json(
        {"schemaVersion": LEDGER_SCHEMA_VERSION, "target": target, "files": dict(sorted(ledger_files.items()))}
    ) + b"\n"
    operations.append(Operation(
        kind="ledger", path=LEDGER_FILENAME, payload=ledger_payload, metadata=(("phase", "ledger"),),
    ))
    operations.append(Operation(
        kind="cleanup-backups", path="backups", paths=tuple(old_backup_paths), metadata=(("phase", "ledger"),),
    ))
    ordered = _order_operations(backups.operations + operations)

    snapshot_rels = set(resolved.files) | set(obsolete_files) | set(ledger or {}) | set(old_backup_paths)
    snapshot_rels.add(LEDGER_FILENAME)
    if cfg.get("configFile"):
        snapshot_rels.add(str(cfg["configFile"]))
    snapshot = _snapshot_for(destination, repo, ordered, snapshot_rels, fs)
    plan_data = {
        "operation": "push", "target": target, "repo": repo.as_posix(),
        "destination": destination.as_posix(), "dryRun": dry_run, "prune": prune,
        "backupBase": backup_base.as_posix(),
        "snapshot": [_observation_key(item) for item in snapshot],
        "operations": [_operation_data(item) for item in ordered],
    }
    unchanged_count = sum(
        1 for rel, payload in resolved.files.items()
        if fs.observe(destination / rel).is_file and fs.read_bytes(destination / rel) == payload
    )
    summary = PlanSummary(
        unchanged_count=unchanged_count,
        modified_stale_paths=tuple(sorted(modified_stale)),
        pruned_backups=tuple(old_backup_paths),
        disabled_plugin_files=tuple(sorted(resolved.disabled_plugin_files)),
        ledger_entries=len(ledger_files),
        manifest_entries=len(resolved.files),
    )
    return DistributionPlan(
        operation="push", target=target, repo_root=repo.as_posix(), destination=destination.as_posix(),
        dry_run=dry_run, prune=prune, identity=_plan_identity(plan_data), snapshot=snapshot,
        operations=ordered, backup_base=backup_base.as_posix(), warnings=tuple(resolved.warnings),
        summary=summary,
    )


# ---------------------------------------------------------------------------
# pull planning

def _pull_skip(path: str, reason: str) -> Operation:
    return Operation(kind="pull-skip", path=path, reason=reason)


def plan_pull(
    target: str,
    repo: Path,
    live_dir: Path | None,
    dry_run: bool,
    *,
    fs: FileSystem,
) -> DistributionPlan:
    """Freeze pull source precedence and payloads before any mutation."""
    repo = Path(repo)
    cfg = load_target(target, repo)
    destination = _resolve_destination(cfg, live_dir)
    if not fs.observe(destination).exists:
        raise FileNotFoundError(f"live ディレクトリが存在しません: {destination}")
    resolved = manifest(target, repo, cfg=cfg)
    drifts = _manifest_drifts(destination, cfg, resolved, fs)
    distribute = cfg.get("distribute", {})
    uninit_submodules = uninitialized_submodule_paths(repo)
    operations: list[Operation] = []
    snapshot_paths: list[Path] = []
    for drift in drifts:
        if drift.kind == "mode":
            operations.append(_pull_skip(drift.path, "mode（実行ビットのみの差分。--push で補正する）"))
            continue
        if drift.kind == "unreconciled":
            operations.append(_pull_skip(drift.path, "settingsSync checkOnlyKeys（live-first キー。SSOT テンプレートへ手動で還流する）"))
            continue
        if drift.kind != "changed":
            operations.append(_pull_skip(drift.path, "missing（live に存在しないため pull できない）"))
            continue
        spec_info = find_spec_for_path(distribute, drift.path)
        if spec_info is None:
            operations.append(_pull_skip(drift.path, "distribute manifest 外のパス"))
            continue
        dest_key, entry = spec_info
        if entry.get("transform"):
            operations.append(_pull_skip(drift.path, f"transform 適用 dest（{dest_key}）。/sync-settings --pull を使え"))
            continue
        source = entry.get("source")
        if source is None:
            operations.append(_pull_skip(drift.path, "source 未定義"))
            continue
        sources = source if isinstance(source, list) else [source]
        if dest_key.endswith("/"):
            rel_in_source = drift.path[len(dest_key):]
            candidate_path = lambda src_rel: repo / src_rel.rstrip("/") / rel_in_source
        else:
            candidate_path = lambda src_rel: repo / src_rel
        winning_source, existing_sources, blocking = resolve_pull_source(
            sources, candidate_path, uninit_submodules
        )
        if blocking:
            operations.append(_pull_skip(
                drift.path,
                f"submodule 未取得のため書き戻し先を判定できない（{', '.join(blocking)}）。取得してから再実行せよ",
            ))
            continue
        if winning_source.rstrip("/") == CURATED_SKILLS_SOURCE:
            operations.append(_pull_skip(
                drift.path,
                "curated skill（upstream が正本。rulesync 側で直して rulesync install を再実行せよ）",
            ))
            continue
        source_path = candidate_path(winning_source)
        operations.append(Operation(
            kind="pull", path=drift.path, payload=fs.read_bytes(destination / drift.path),
            source_path=source_path.as_posix(),
            metadata=(("phase", "pull"), ("existingSources", str(len(existing_sources))), ("winningSource", str(winning_source))),
        ))
        snapshot_paths.extend((destination / drift.path, source_path))
    snapshot: list[Observation] = []
    seen: set[str] = set()
    for path in snapshot_paths:
        if path.as_posix() not in seen:
            snapshot.append(fs.observe(path))
            seen.add(path.as_posix())
    plan_data = {
        "operation": "pull", "target": target, "repo": repo.as_posix(),
        "destination": destination.as_posix(), "dryRun": dry_run,
        "snapshot": [_observation_key(item) for item in snapshot],
        "operations": [_operation_data(item) for item in operations],
    }
    return DistributionPlan(
        operation="pull", target=target, repo_root=repo.as_posix(), destination=destination.as_posix(),
        dry_run=dry_run, prune=False, identity=_plan_identity(plan_data), snapshot=tuple(snapshot),
        operations=tuple(operations), warnings=tuple(resolved.warnings),
        summary=PlanSummary(manifest_entries=len(resolved.files)),
    )


# ---------------------------------------------------------------------------
# apply

def _event_for(index: int, operation: Operation, status: OperationStatus, reason: str | None = None) -> ApplyEvent:
    return ApplyEvent(
        index=index,
        kind=operation.kind,
        path=operation.path,
        status=status,
        reason=reason,
        backup_path=operation.backup_path,
    )


def _result_from_events(
    plan: DistributionPlan,
    status: ApplyStatus,
    events: Sequence[ApplyEvent],
    error: str | None = None,
    exit_code: int | None = None,
) -> ApplyResult:
    applied = sum(event.status == OperationStatus.APPLIED for event in events)
    failed = sum(event.status == OperationStatus.FAILED for event in events)
    if exit_code is None:
        exit_code = 0 if status in (ApplyStatus.APPLIED, ApplyStatus.DRY_RUN) else 1
    return ApplyResult(
        status=status,
        plan_identity=plan.identity,
        events=tuple(events),
        error=error,
        applied_count=applied,
        failed_count=failed,
        exit_code=exit_code,
    )


_PAYLOAD_KINDS = frozenset({
    "add", "overwrite", "ledger", "settings-template", "settings-sync",
    "settings-overlay", "extras-overlay", "pull",
})
_REMOVE_KINDS = frozenset({"remove-obsolete", "remove-managed", "prune"})
_NOOP_KINDS = frozenset({"warning", "pull-skip", "mode-symlink"})


def _apply_operation(plan: DistributionPlan, operation: Operation, fs: FileSystem) -> None:
    """Execute one already-frozen operation; never consult distribution rules."""
    # Path.__truediv__ keeps an absolute right operand, so absolute operation
    # paths (backup targets, pull sources) resolve unchanged.
    destination = plan.destination_path / operation.path
    kind = operation.kind
    if kind == "backup":
        if not operation.backup_path:
            raise ValueError("backup operation is missing backup_path")
        backup = plan.destination_path / operation.backup_path
        fs.mkdir(backup.parent)
        if operation.metadata_map.get("strategy") == "copy":
            fs.copy(destination, backup)
        else:
            fs.rename(destination, backup)
        return
    if kind in _PAYLOAD_KINDS:
        if operation.payload is None:
            raise ValueError(f"{kind} operation payload is missing")
        write_path = plan.repo_path / (operation.source_path or "") if kind == "pull" else destination
        fs.mkdir(write_path.parent)
        fs.atomic_write(write_path, operation.payload)
        return
    if kind in _REMOVE_KINDS:
        observed = fs.observe(destination)
        if not (observed.exists or observed.is_symlink):
            return
        fs.remove(destination)
        stop = (
            plan.destination_path / operation.metadata_map["base"]
            if kind == "prune" and operation.metadata_map.get("base")
            else plan.destination_path
        )
        _remove_empty_dirs(fs, destination.parent, stop)
        return
    if kind == "chmod":
        if operation.mode is None:
            raise ValueError("chmod operation is missing mode")
        fs.chmod(destination, operation.mode)
        return
    if kind == "cleanup-backups":
        for rel in operation.paths:
            path = plan.destination_path / rel
            observed = fs.observe(path)
            if observed.exists or observed.is_symlink:
                fs.remove_tree(path)
        return
    if kind in _NOOP_KINDS:
        return
    raise ValueError(f"unknown distribution operation: {kind}")


def _apply_operations(plan: DistributionPlan, fs: FileSystem) -> ApplyResult:
    """Execute every operation in the supplied immutable plan."""
    events: list[ApplyEvent] = []
    first_error: str | None = None
    for index, operation in enumerate(plan.operations):
        if plan.dry_run:
            events.append(_event_for(index, operation, OperationStatus.PLANNED))
            continue
        try:
            _apply_operation(plan, operation, fs)
        except Exception as error:
            message = str(error)
            events.append(_event_for(index, operation, OperationStatus.FAILED, message))
            first_error = first_error or message
            if plan.operation != "pull":
                events.extend(
                    _event_for(i, op, OperationStatus.SKIPPED, "not executed after failure")
                    for i, op in enumerate(plan.operations[index + 1 :], index + 1)
                )
                return _result_from_events(plan, ApplyStatus.PARTIAL_FAILURE, events, error=first_error, exit_code=1)
            continue
        events.append(_event_for(index, operation, OperationStatus.APPLIED))
    if first_error is not None:
        return _result_from_events(plan, ApplyStatus.PARTIAL_FAILURE, events, error=first_error, exit_code=1)
    return _result_from_events(plan, ApplyStatus.DRY_RUN if plan.dry_run else ApplyStatus.APPLIED, events)


def apply(plan: DistributionPlan, *, fs: FileSystem) -> ApplyResult:
    """Apply exactly the supplied plan, rejecting stale destination state."""
    if not isinstance(plan, DistributionPlan):
        return ApplyResult(
            status=ApplyStatus.INVALID,
            plan_identity="",
            error="apply expects DistributionPlan",
            exit_code=1,
        )
    lock = contextlib.nullcontext() if plan.dry_run else fs.lock(plan.destination_path)
    try:
        with lock:
            if not _snapshot_matches(plan, fs):
                events = tuple(
                    _event_for(index, operation, OperationStatus.SKIPPED, "destination changed after plan")
                    for index, operation in enumerate(plan.operations)
                )
                return _result_from_events(
                    plan, ApplyStatus.STALE, events, error="destination changed after plan", exit_code=1,
                )
            return _apply_operations(plan, fs)
    except Exception as error:
        events = tuple(
            _event_for(index, operation, OperationStatus.SKIPPED, "lock or preflight failure")
            for index, operation in enumerate(plan.operations)
        )
        return _result_from_events(plan, ApplyStatus.INVALID, events, error=str(error), exit_code=1)


__all__ = [
    "ApplyEvent",
    "ApplyResult",
    "ApplyStatus",
    "DistributionInspection",
    "DistributionPlan",
    "FileSystem",
    "Observation",
    "Operation",
    "OperationStatus",
    "PathFileSystem",
    "PlanSummary",
    "SettingsChange",
    "apply",
    "inspect",
    "plan_pull",
    "plan_push",
]
