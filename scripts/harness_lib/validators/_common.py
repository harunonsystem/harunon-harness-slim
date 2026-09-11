"""validators 共通のヘルパー（JSON の安全読み・target 列挙・submodule 判定）。"""
from __future__ import annotations

from pathlib import Path

from ..config import target_config_paths
from ..jsonio import JsonLoadError, load_json_object
from ..resolver import in_uninitialized_submodule, uninitialized_submodule_paths
from ..validator_registry import Finding

# extras submodule のルート（未取得判定に使う。distribute source と同じ規約）
EXTRAS_ROOT = "packages/extras/_active"


def load_json_or_finding(path: Path, repo_root: Path, check: str) -> tuple[dict | None, list[Finding]]:
    """JSON を読む。壊れていれば (None, [Finding]) を返し、呼び出し側は意味検査を skip する。"""
    try:
        return load_json_object(path), []
    except JsonLoadError as error:
        return None, [
            Finding(
                check=check,
                level="error",
                message=f"{path.relative_to(repo_root)}: {error.reason}",
            )
        ]


def target_configs(repo_root: Path, check: str) -> tuple[list[tuple[Path, dict]], list[Finding]]:
    """packages/targets/*/config.json を (path, dict) で返す。壊れた config は Finding にする。

    列挙は config.target_config_paths（唯一の target 列挙）に委ねる。packages/targets
    が無い repo root では空を返す（`.iterdir()` の FileNotFoundError にしない）。
    """
    configs: list[tuple[Path, dict]] = []
    findings: list[Finding] = []
    for config_path in target_config_paths(repo_root):
        data, errors = load_json_or_finding(config_path, repo_root, check)
        findings.extend(errors)
        if data is not None:
            configs.append((config_path, data))
    return configs, findings


def uninitialized_submodules(repo_root: Path) -> list[str]:
    return uninitialized_submodule_paths(repo_root)


def is_extras_uninitialized(repo_root: Path) -> bool:
    """extras submodule（packages/extras/_active）が未取得かどうか。"""
    return in_uninitialized_submodule(EXTRAS_ROOT, uninitialized_submodules(repo_root))


def distribute_sources(spec: dict) -> list:
    """distribute entry の source を常に list として返す（文字列/配列両対応）。"""
    source = spec.get("source")
    return source if isinstance(source, list) else [source]


__all__ = [
    "EXTRAS_ROOT",
    "distribute_sources",
    "in_uninitialized_submodule",
    "is_extras_uninitialized",
    "load_json_or_finding",
    "target_configs",
    "uninitialized_submodules",
]
