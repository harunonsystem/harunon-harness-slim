"""配布宣言（packages/targets/*/config.json）と配布物の実在・配線を検証する。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..config import target_config_errors, target_config_paths
from ..hook_pipeline import MANUAL_HOOK_SCRIPTS
from ..jsonio import JsonLoadError
from ..resolver import CURATED_SKILLS_SOURCE
from ..validator_registry import Finding
from ._common import distribute_sources, in_uninitialized_submodule, target_configs, uninitialized_submodules



def check_config_schema(repo_root: Path) -> list[Finding]:
    """config.json をスキーマで構造検証する"""
    schema_path = repo_root / "schemas" / "target-config.schema.json"
    if not schema_path.is_file():
        return []
    findings: list[Finding] = []
    for config_path in target_config_paths(repo_root):
        try:
            errors = target_config_errors(config_path, repo_root)
        except JsonLoadError as error:
            errors = [error.reason]
        for err in errors:
            findings.append(
                Finding(
                    check="config-schema",
                    level="error",
                    message=f"{config_path.relative_to(repo_root)}: {err}",
                )
            )
    return findings


def check_runtime_adapter_wiring(repo_root: Path) -> list[Finding]:
    """Ensure curated runtime artifacts are reachable, with no dead bundled modules."""
    findings: list[Finding] = []

    # Codex の hook 一覧は dispatcher / builder が hook-pipeline.json から導出するため、
    # ここでの集合比較は不要になった（再ハードコードの禁止は hook-pipeline チェックが担う）。

    umbrella = repo_root / "packages/runtimes/opencode/harunon.js"
    modules_dir = repo_root / "packages/core/opencode-plugins"
    if umbrella.is_file() and modules_dir.is_dir():
        umbrella_imports = set(re.findall(
            r'harunon-opencode/([^"/]+\.js)"', umbrella.read_text(encoding="utf-8")
        ))
        available = {path.name for path in modules_dir.glob("*.js")}
        # 到達可能 = umbrella の直接 import + そこから module 間の相対 import
        # （`./tool-cwd.js` のような共有 helper）で辿れるもの。直接 import だけを
        # 見ると helper を置くたびに umbrella へ意味のない import を足すことになる。
        imported = set()
        queue = sorted(umbrella_imports)
        while queue:
            name = queue.pop()
            if name in imported:
                continue
            imported.add(name)
            module = modules_dir / name
            if not module.is_file():
                continue
            queue.extend(re.findall(
                r'from\s+"\./([^"/]+\.js)"', module.read_text(encoding="utf-8")
            ))
        if imported != available:
            findings.append(Finding(
                check="runtime-adapter-wiring",
                level="error",
                message=(
                    "OpenCode umbrella と runtime modules が不一致: "
                    f"missing-import={sorted(available - imported)}, "
                    f"missing-module={sorted(imported - available)}"
                ),
            ))
    return findings


def check_target_config_sources(repo_root: Path) -> list[Finding]:
    configs, findings = target_configs(repo_root, "target-config-sources")
    if not configs and not findings:
        return []

    uninit_submodules = uninitialized_submodules(repo_root)
    for config_path, config in configs:
        distribute = config.get("distribute", {})
        if not isinstance(distribute, dict):
            continue
        for dest, spec in distribute.items():
            if not isinstance(spec, dict):
                continue
            source = spec.get("source")
            if not source:
                continue
            for entry in distribute_sources(spec):
                if (repo_root / entry).exists():
                    continue
                # CI 等で private submodule / rulesync install 未実行の checkout は欠如扱いにしない
                # （resolver._resolve_source_files と同じ skip 判定。ADR-011 Update 2026-08-30）
                is_curated = entry.rstrip("/") == CURATED_SKILLS_SOURCE
                in_uninit_submodule = in_uninitialized_submodule(entry, uninit_submodules)
                skip_reason = "rulesync install 未実行" if is_curated else "submodule 未取得"
                findings.append(
                    Finding(
                        check="target-config-sources",
                        level="warn" if (is_curated or in_uninit_submodule) else "error",
                        message=(
                            f"{config_path.relative_to(repo_root)}: "
                            f"distribute[{dest!r}] source が存在しません: {entry}"
                            + (f"（{skip_reason}のため警告扱い）" if (is_curated or in_uninit_submodule) else "")
                        ),
                    )
                )
    return findings


def _is_git_ignored(repo_root: Path, path: Path) -> bool:
    """path が git の無視対象なら True。git 不在時は False（安全側で検査続行）。"""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=repo_root,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def check_no_symlinks_in_distribution_sources(repo_root: Path) -> list[Finding]:
    """配布 source ディレクトリ配下に symlink が混入していないか検証する。

    symlink が混じると、resolver._collect_dir がリンク先の内容を無警告で
    デリファレンスして配布してしまう（リンク切れは無警告で欠落する）。
    配布ツリーに symlink が入った時点で commit 時に検出する。
    """
    configs, findings = target_configs(repo_root, "no-symlinks-in-distribution-sources")
    seen_sources: set[str] = set()

    for _config_path, config in configs:
        distribute = config.get("distribute", {})
        if not isinstance(distribute, dict):
            continue
        for spec in distribute.values():
            if not isinstance(spec, dict):
                continue
            if not spec.get("source"):
                continue
            for entry in distribute_sources(spec):
                if entry in seen_sources:
                    continue
                seen_sources.add(entry)

                src_path = repo_root / entry
                if not src_path.is_dir():
                    # 単一ファイル source（source ディレクトリのみ検査対象）。
                    # 未取得 submodule 等で存在しない場合も対象外
                    continue

                for child in sorted(src_path.rglob("*")):
                    if not child.is_symlink():
                        continue
                    # gitignore 対象（config.yml 等のローカル専用ファイル）は
                    # 追跡・配布されず、fresh checkout / CI にも存在しない。
                    # ユーザーがローカルで override を symlink 配線する正当用途
                    # （skill-overrides 等）なので検査対象から除外する。
                    if _is_git_ignored(repo_root, child):
                        continue
                    findings.append(
                        Finding(
                            check="no-symlinks-in-distribution-sources",
                            level="error",
                            message=(
                                f"{child.relative_to(repo_root)}: 配布 source 配下に "
                                "symlink があります"
                                "（無警告でデリファレンス/欠落するため禁止）"
                            ),
                        )
                    )
    return findings


def check_hooks_wiring(repo_root: Path) -> list[Finding]:
    """settings.json の hook 参照 ↔ hooks/ 実ファイルの突合。

    settings.json は claude 専用テンプレートなので `~/.claude/hooks/` パスを
    決め打ちで抽出する（他ターゲットに hooks 配布の概念はない）。
    """
    settings_path = repo_root / "packages" / "core" / "settings.json"
    hooks_dir = repo_root / "packages" / "core" / "hooks"
    if not settings_path.is_file() or not hooks_dir.is_dir():
        return []

    settings_text = settings_path.read_text(encoding="utf-8")
    referenced = set(re.findall(r"~/\.claude/hooks/([\w.-]+)", settings_text))
    actual = {child.name for child in hooks_dir.iterdir() if child.is_file()}

    findings: list[Finding] = []
    for name in sorted(referenced - actual):
        findings.append(
            Finding(
                check="hooks-wiring",
                level="error",
                message=f"settings.json が参照する hook が存在しません: {name}",
            )
        )
    for name in sorted(actual - referenced - MANUAL_HOOK_SCRIPTS):
        findings.append(
            Finding(
                check="hooks-wiring",
                level="warn",
                message=f"settings.json に配線されていない hook: {name}",
            )
        )
    return findings


CHECKS = {
    "config-schema": check_config_schema,
    "runtime-adapter-wiring": check_runtime_adapter_wiring,
    "target-config-sources": check_target_config_sources,
    "no-symlinks-in-distribution-sources": check_no_symlinks_in_distribution_sources,
    "hooks-wiring": check_hooks_wiring,
}
