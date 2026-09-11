"""harness_lib.public_slim — 公開 slim 配布物の生成とゲート。

`packages/public-slim/manifest.json` が「何を出し何を出さないか」を宣言し、このモジュールが
それを実行する。生成物は 2 つ:

- harunon-harness-slim: SSOT の allowlist コピー（repo レイアウトのまま）
- harunon-pi-agent-slim: 生成した harness-slim から distribute.py pi で組んだ pi configDir
  payload + install/validate スクリプト。private tree からではなく slim tree から導くので、
  slim で落としたもの（extras の rules / RTK.md 等）が pi payload に混ざらない

ゲートに使う値（社名・submodule 名・ローカルユーザー名）は manifest に持たない。manifest
自身が公開対象なので、そこに固有名を書けばそれ自体が漏洩経路になる。source 名 → 読み出し先
の対応は PATTERN_SOURCES がここ 1 箇所で持つ。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .includes import INCLUDE_RE

MANIFEST_REL = "packages/public-slim/manifest.json"
HARNESS_SLIM_DIR = "harunon-harness-slim"
PI_AGENT_SLIM_DIR = "harunon-pi-agent-slim"
PI_AGENT_STATIC_REL = "packages/public-slim/pi-agent"
PI_TARGET = "pi"
PI_CONFIG_REL = "packages/targets/pi/config.json"
INSTALL_MANIFEST_NAME = "install-manifest.json"
# distribute --push が dest に残す運用状態。pi payload は rsync ベースの install.sh で配るので
# ledger / backup は持たない（持つと生成マシンの repo パスが payload に載る）
DISTRIBUTE_STATE_ARTIFACTS = (".harness-distributed.json", "backups")

# source 名 → 読み出し先の契約。ファイル名・キー名をここ以外に散らさない。
BLOCKED_TERMS_FILE = ".env"
BLOCKED_TERMS_KEY = "BLOCKED_TERMS"
GITMODULES_FILE = ".gitmodules"

SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".pytest_cache", ".venv"})


class SlimBuildError(Exception):
    """manifest の宣言と実体の不一致、またはゲート違反。呼び出し元は exit 2 にする。"""


# ---------------------------------------------------------------------------
# manifest / file enumeration


def load_manifest(repo: Path) -> dict:
    path = repo / MANIFEST_REL
    if not path.is_file():
        raise SlimBuildError(f"manifest が無い: {MANIFEST_REL}")
    return json.loads(path.read_text(encoding="utf-8"))


def enumerate_files(repo: Path) -> list[str]:
    """公開候補の相対パス一覧。

    git 管理下なら `git ls-files`（追跡ファイルのみ。.env / build/ / skills/ 等の untracked と
    submodule の gitlink は自然に落ちる）。git が無い tree（テストの temp copy）は walk に
    fallback し、.gitignore 相当の判定はしない。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--cached"],
            capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        out = None
    if out is not None:
        rels = [p.decode("utf-8") for p in out.split(b"\0") if p]
        return sorted(r for r in rels if (repo / r).is_file())
    rels = []
    for path in repo.rglob("*"):
        rel = path.relative_to(repo)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.is_file():
            rels.append(rel.as_posix())
    return sorted(rels)


def _matches(path: str, prefixes: list[str]) -> bool:
    return any(path == p or path.startswith(p) for p in prefixes)


def select_files(files: list[str], manifest: dict) -> list[str]:
    include = manifest["include"]
    exclude = manifest.get("exclude", [])
    return [f for f in files if _matches(f, include) and not _matches(f, exclude)]


# ---------------------------------------------------------------------------
# harness-slim tree


def _copy_selected(repo: Path, selected: list[str], out: Path) -> None:
    for rel in selected:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, dest)


def _drop_dangling_include_lines(out: Path) -> list[str]:
    """出力 tree に存在しない fragment を指す include 行を落とす。

    残すと expand_includes が FileNotFoundError で fail fast し、slim 側で配布が回らない。
    判定は「include 先が出力 tree に無い」の完全一致なので exclude の宣言から機械的に導ける。
    """
    dropped: list[str] = []
    for path in out.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.relative_to(out).parts):
            continue
        text = path.read_text(encoding="utf-8")
        if "<!--" not in text:
            continue
        kept: list[str] = []
        changed = False
        for line in text.splitlines(keepends=True):
            m = INCLUDE_RE.match(line.rstrip("\n"))
            if m and not (out / m.group("path")).is_file():
                dropped.append(f"{path.relative_to(out).as_posix()}: {m.group('path')}")
                changed = True
                continue
            kept.append(line)
        if changed:
            path.write_text("".join(kept), encoding="utf-8")
    return dropped


def _write_json_like_source(path: Path, data: dict) -> None:
    # target config は tab インデント。生成物の diff を SSOT と比べやすいよう揃える
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8"
    )


def _drop_excluded_sources(out: Path) -> list[str]:
    """packages/targets/*/config.json の distribute エントリから、出力 tree に無い source を落とす。

    source が文字列なら実体が無ければエントリごと削除、リストなら無い要素だけ落とし、空に
    なったらエントリ削除。settingsSync.source が無ければ settingsSync を落とす。
    """
    dropped: list[str] = []
    for config_path in sorted((out / "packages/targets").glob("*/config.json")):
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        label = config_path.relative_to(out).as_posix()
        changed = False
        distribute = cfg.get("distribute") or {}
        for dest_key in list(distribute):
            spec = distribute[dest_key]
            source = spec.get("source")
            if isinstance(source, str):
                if not (out / source).exists():
                    del distribute[dest_key]
                    dropped.append(f"{label}: {dest_key} ({source})")
                    changed = True
            elif isinstance(source, list):
                present = [s for s in source if (out / s).exists()]
                if present != source:
                    changed = True
                    missing = [s for s in source if s not in present]
                    if not present:
                        del distribute[dest_key]
                        dropped.append(f"{label}: {dest_key} ({', '.join(missing)})")
                    else:
                        spec["source"] = present
                        dropped.append(f"{label}: {dest_key} members {', '.join(missing)}")
        sync = cfg.get("settingsSync")
        if isinstance(sync, dict) and isinstance(sync.get("source"), str):
            if not (out / sync["source"]).exists():
                del cfg["settingsSync"]
                dropped.append(f"{label}: settingsSync ({sync['source']})")
                changed = True
        if changed:
            _write_json_like_source(config_path, cfg)
    return dropped


def _drop_ghost_command_rows(out: Path) -> list[str]:
    """commands.md の表から、出力 tree に skill 実体が無いコマンドの行を落とす。

    private では restricted / extras / rulesync curated の skill も commands.md に載るが、slim には
    その実体が無く commands-vs-skills が error になる。known の判定は validator と同じ関数を使う。
    表以外の行に ghost が残った場合は落とさず SlimBuildError にする（手で SSOT を直す）。
    """
    from .validators.skills import (  # 遅延 import: validators は public_slim を import しない
        BUILTIN_COMMANDS,
        _extract_commands_from_commands_md,
        harness_skill_names,
    )

    commands_md = out / "packages/core/commands.md"
    if not commands_md.is_file():
        return []
    known = harness_skill_names(out) | BUILTIN_COMMANDS
    ghosts = _extract_commands_from_commands_md(commands_md) - known
    if not ghosts:
        return []
    row_re = re.compile(r"^\|\s*`/(?P<name>[^`:]+)`\s*\|")
    kept: list[str] = []
    dropped: list[str] = []
    for line in commands_md.read_text(encoding="utf-8").splitlines(keepends=True):
        m = row_re.match(line)
        if m and m.group("name") in ghosts:
            dropped.append(m.group("name"))
            continue
        kept.append(line)
    commands_md.write_text("".join(kept), encoding="utf-8")
    remaining = _extract_commands_from_commands_md(commands_md) - known
    if remaining:
        raise SlimBuildError(
            "commands.md の表以外に slim に無い skill への参照が残っている: "
            + ", ".join(sorted(remaining))
        )
    return sorted(dropped)


def _rewrite_scale_counts(out: Path) -> list[str]:
    """CONTEXT.md「管理規模」の数字を出力 tree の実体で書き直す（数え方は validator と共有）。"""
    from .validators.context_md import scale_actuals, scale_count_pattern

    context_md = out / "CONTEXT.md"
    if not context_md.is_file():
        return []
    text = context_md.read_text(encoding="utf-8")
    changes: list[str] = []
    for category, actual in scale_actuals(out).items():
        if actual is None:
            continue
        pattern = scale_count_pattern(category)
        m = pattern.search(text)
        if m and int(m.group(2)) != actual:
            changes.append(f"{category}: {m.group(2)} -> {actual}")
            text = pattern.sub(lambda mm: f"{mm.group(1)}{actual}", text, count=1)
    if changes:
        context_md.write_text(text, encoding="utf-8")
    return changes


def _add_files(repo: Path, manifest: dict, out: Path) -> None:
    for dest_rel, source_rel in manifest.get("addFiles", {}).items():
        source = repo / source_rel
        if not source.is_file():
            raise SlimBuildError(f"addFiles の source が無い: {source_rel}")
        dest = out / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


@dataclass
class HarnessSlimReport:
    included: list[str]
    dropped_includes: list[str] = field(default_factory=list)
    dropped_sources: list[str] = field(default_factory=list)
    dropped_commands: list[str] = field(default_factory=list)
    scale_rewrites: list[str] = field(default_factory=list)


def build_harness_slim(repo: Path, manifest: dict, out: Path) -> HarnessSlimReport:
    for rel in manifest["include"]:
        if not (repo / rel).exists():
            raise SlimBuildError(f"include の実体が無い: {rel}")
    selected = select_files(enumerate_files(repo), manifest)
    if not selected:
        raise SlimBuildError("include に一致するファイルが 0 件")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    _copy_selected(repo, selected, out)
    report = HarnessSlimReport(included=selected)
    if manifest.get("dropIncludes"):
        report.dropped_includes = _drop_dangling_include_lines(out)
    if manifest.get("dropExcludedSources"):
        report.dropped_sources = _drop_excluded_sources(out)
    _add_files(repo, manifest, out)
    # addFiles（lessons の空 ledger 等）を置いた後に、出力 tree の実体で数え直す
    if manifest.get("dropGhostCommands"):
        report.dropped_commands = _drop_ghost_command_rows(out)
    if manifest.get("rewriteScaleCounts"):
        report.scale_rewrites = _rewrite_scale_counts(out)
    return report


# ---------------------------------------------------------------------------
# pi-agent-slim payload


def build_pi_agent_slim(repo: Path, harness_slim: Path, out: Path) -> dict:
    """harness-slim tree から pi payload を組む。戻り値は install-manifest の内容。"""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    result = subprocess.run(
        [
            sys.executable, str(harness_slim / "scripts/distribute.py"), PI_TARGET,
            "--push", "--dir", str(out), "--repo-root", str(harness_slim),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SlimBuildError(
            f"distribute.py {PI_TARGET} --push が失敗 (exit {result.returncode}):\n"
            f"{result.stdout}{result.stderr}"
        )
    for name in DISTRIBUTE_STATE_ARTIFACTS:
        path = out / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    static = repo / PI_AGENT_STATIC_REL
    if not static.is_dir():
        raise SlimBuildError(f"pi-agent の静的ファイルが無い: {PI_AGENT_STATIC_REL}")
    shutil.copytree(static, out, dirs_exist_ok=True)

    cfg = json.loads((harness_slim / PI_CONFIG_REL).read_text(encoding="utf-8"))
    managed = {key.rstrip("/") for key in (cfg.get("distribute") or {})}
    sync = cfg.get("settingsSync") or {}
    if sync:
        # settingsSync は distribute エントリではないが payload に settings.json を書くので、
        # 管理対象の棚卸しとして載せる（install.sh は rsync ではなく settingsKeys の merge で扱う）
        managed.add(cfg.get("configFile", "settings.json"))
    managed = sorted(managed)
    install_manifest = {
        "_comment": (
            "build-public-slim.py が harness-slim の packages/targets/pi/config.json から生成。"
            "install.sh はここを読んで rsync する管理パスと settings.json の同期キーを決める"
            "（配列を install.sh に直書きしない）"
        ),
        "managedPaths": managed,
        "settingsFile": cfg.get("configFile", "settings.json"),
        "settingsKeys": list(sync.get("keys", [])),
    }
    (out / INSTALL_MANIFEST_NAME).write_text(
        json.dumps(install_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return install_manifest


# ---------------------------------------------------------------------------
# gate


def _blocked_terms(repo: Path, env_file: Path | None = None) -> list[str]:
    """社名・個人名の既存 SSOT。.githooks/pre-commit と同じソース（.env の BLOCKED_TERMS）を読む。"""
    path = env_file if env_file is not None else repo / BLOCKED_TERMS_FILE
    if not path.is_file():
        return []
    prefix = BLOCKED_TERMS_KEY + "="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            raw = line[len(prefix):].strip().strip('"')
            return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _submodule_names(repo: Path, env_file: Path | None = None) -> list[str]:
    """.gitmodules に宣言された submodule の URL から repo 名を導く（値を持たない）。"""
    gitmodules = repo / GITMODULES_FILE
    if not gitmodules.is_file():
        return []
    names = []
    for line in gitmodules.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("url"):
            url = stripped.split("=", 1)[1].strip()
            names.append(url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))
    return names


def _local_home(repo: Path, env_file: Path | None = None) -> list[str]:
    """絶対パスの漏れは build を回すマシンの HOME に依存するので実行時に解決する。

    ユーザー名の裸の文字列ではなく HOME のパスで当てる。裸だと GitHub Actions の
    `runner` が hook-runner 等に当たって誤爆する（2026-09-11 に slim の CI で実測）。
    """
    return [str(Path.home())]


PATTERN_SOURCES: dict[str, Callable[[Path, Path | None], list[str]]] = {
    "blockedTerms": _blocked_terms,
    "submoduleNames": _submodule_names,
    "localHome": _local_home,
}


def resolve_gate_patterns(repo: Path, gate: dict, env_file: Path | None = None) -> dict[str, list[str]]:
    resolved: dict[str, list[str]] = {}
    for source in gate["patternSources"]:
        resolver = PATTERN_SOURCES.get(source)
        if resolver is None:
            raise SlimBuildError(f"未知の patternSource: {source}")
        resolved[source] = [p for p in resolver(repo, env_file) if p]
    if gate.get("failClosed") and not resolved.get("blockedTerms"):
        raise SlimBuildError(
            f"blockedTerms が空。{BLOCKED_TERMS_FILE} の {BLOCKED_TERMS_KEY} を設定してください"
            f"（契約は {BLOCKED_TERMS_FILE}.example 参照）。公開は不可逆なのでパターン 0 件では生成しない"
        )
    return resolved


def _text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        data = path.read_bytes()
        if b"\0" in data[:8000]:
            continue
        yield path.relative_to(root).as_posix(), data.decode("utf-8", errors="ignore").lower()


def scan_outputs(roots: dict[str, Path], patterns: list[str]) -> dict[str, list[str]]:
    """pattern（小文字比較）→ ヒットしたファイル（`<root名>/<相対パス>`）。パス名にも当てる。"""
    lowered = [(p, p.lower()) for p in patterns]
    hits: dict[str, list[str]] = {}
    for name, root in roots.items():
        for rel, text in _text_files(root):
            rel_lower = rel.lower()
            for pat, pat_lower in lowered:
                if pat_lower in text or pat_lower in rel_lower:
                    hits.setdefault(pat, []).append(f"{name}/{rel}")
    return hits


@dataclass
class GateResult:
    pattern_count: int
    hits: dict[str, list[str]]
    suspicious: dict[str, list[str]]

    @property
    def ok(self) -> bool:
        return not self.hits


def run_gate(repo: Path, manifest: dict, roots: dict[str, Path], env_file: Path | None = None) -> GateResult:
    gate = manifest["gate"]
    resolved = resolve_gate_patterns(repo, gate, env_file)
    patterns = [p for values in resolved.values() for p in values]
    hits = scan_outputs(roots, patterns)
    suspicious = scan_outputs(roots, list(gate.get("suspiciousPatterns", [])))
    return GateResult(pattern_count=len(patterns), hits=hits, suspicious=suspicious)


def render_gate(result: GateResult) -> str:
    """値（blocked term）は表示しない。件数とファイルだけ出す。"""
    lines = [f"gate: {result.pattern_count} patterns"]
    if not result.hits:
        lines.append("  hits: none")
    for files in result.hits.values():
        lines.append(f"  HIT {len(files)} files")
        lines.extend(f"      {f}" for f in files[:20])
    for pat, files in sorted(result.suspicious.items()):
        lines.append(f"  suspicious [{pat}] {len(files)} files (listed only)")
        lines.extend(f"      {f}" for f in files[:20])
    return "\n".join(lines)


__all__ = [
    "GateResult",
    "HARNESS_SLIM_DIR",
    "HarnessSlimReport",
    "INSTALL_MANIFEST_NAME",
    "MANIFEST_REL",
    "PATTERN_SOURCES",
    "PI_AGENT_SLIM_DIR",
    "PI_AGENT_STATIC_REL",
    "SlimBuildError",
    "build_harness_slim",
    "build_pi_agent_slim",
    "enumerate_files",
    "load_manifest",
    "render_gate",
    "resolve_gate_patterns",
    "run_gate",
    "scan_outputs",
    "select_files",
]
