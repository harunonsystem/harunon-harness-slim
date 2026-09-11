"""portable な model 境界と target projection の socket を検証する。"""
from __future__ import annotations

from pathlib import Path

from .. import model_routing
from ..jsonio import JsonLoadError, load_json_object
from ..validator_registry import Finding
from ._common import distribute_sources, target_configs

CHECK_NAME = "model-portability"
_PORTABLE_DIRS = (
    "packages/core/rules",
    "packages/core/fragments/agents-md",
)
_PORTABLE_FILES = (
    "packages/core/RTK.md",
    "packages/core/commands.md",
)
_DISABLED_SKILLS_PATH = Path("packages/core/disabled-skills.json")
_TARGET_AGENTS_ROOT = Path("packages/targets")


def _load_table(repo_root: Path) -> dict | None:
    try:
        return model_routing.load(repo_root)
    except JsonLoadError:
        return None


def _nonportable_skill_names(repo_root: Path) -> set[str]:
    """disabled-skills.json の common を target-edge skill として扱う。"""
    try:
        data = load_json_object(repo_root / _DISABLED_SKILLS_PATH)
    except JsonLoadError:
        return set()
    common = data.get("common")
    if not isinstance(common, list):
        return set()
    return {name for name in common if isinstance(name, str) and name}


def _portable_files(repo_root: Path) -> list[Path]:
    paths = [
        path
        for relative_dir in _PORTABLE_DIRS
        for path in (repo_root / relative_dir).rglob("*.md")
    ]
    targets_dir = repo_root / _TARGET_AGENTS_ROOT
    if targets_dir.is_dir():
        paths.extend(targets_dir.glob("*/AGENTS.md"))

    skills_dir = repo_root / "packages/core/skills"
    excluded_skills = _nonportable_skill_names(repo_root)
    if skills_dir.is_dir():
        paths.extend(
            path
            for path in skills_dir.rglob("*.md")
            if path.relative_to(skills_dir).parts[0] not in excluded_skills
        )
    paths.extend(
        repo_root / relative_path
        for relative_path in _PORTABLE_FILES
        if (repo_root / relative_path).is_file()
    )
    return sorted(path for path in set(paths) if path.is_file())


def _model_ids(table: dict) -> tuple[str, ...]:
    models = table.get("models")
    if not isinstance(models, dict):
        return ()
    return tuple(sorted({value for value in models.values() if isinstance(value, str) and value}))


def _portable_findings(repo_root: Path, model_ids: tuple[str, ...]) -> list[Finding]:
    findings: list[Finding] = []
    for path in _portable_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for model_id in model_ids:
            if model_id not in text:
                continue
            findings.append(
                Finding(
                    check=CHECK_NAME,
                    level="error",
                    message=(
                        f"{path.relative_to(repo_root)}: portable source に model id "
                        f"{model_id!r} を直接書かない（target adapter の projection に置く）"
                    ),
                )
            )
    return findings


def _config_sources(config: dict) -> list[str]:
    sources: list[str] = []

    settings_sync = config.get("settingsSync")
    if isinstance(settings_sync, dict) and isinstance(settings_sync.get("source"), str):
        sources.append(settings_sync["source"])

    distribute = config.get("distribute")
    if isinstance(distribute, dict):
        for spec in distribute.values():
            if not isinstance(spec, dict):
                continue
            sources.extend(source for source in distribute_sources(spec) if isinstance(source, str))
    return sources


def _owns_path(source: str, path: str) -> bool:
    source = source.rstrip("/")
    return path == source or path.startswith(f"{source}/")


def _socket_findings(repo_root: Path, table: dict) -> list[Finding]:
    configs, findings = target_configs(repo_root, CHECK_NAME)
    configs_by_runtime = {path.parent.name: config for path, config in configs}

    routes = table.get("routes")
    if not isinstance(routes, list):
        return findings

    for route in routes:
        if not isinstance(route, dict):
            continue
        runtime = route.get("runtime")
        projections = route.get("projections")
        if not isinstance(runtime, str) or not isinstance(projections, list):
            continue
        config = configs_by_runtime.get(runtime)
        if config is None:
            continue
        sources = _config_sources(config)
        for projection in projections:
            if not isinstance(projection, dict):
                continue
            projection_path = projection.get("path")
            if not isinstance(projection_path, str):
                continue
            if any(_owns_path(source, projection_path) for source in sources):
                continue
            findings.append(
                Finding(
                    check=CHECK_NAME,
                    level="error",
                    message=(
                        f"{runtime}: routing projection {projection_path!r} が "
                        "target config の adapter socket（settingsSync/distribute source）に "
                        "宣言されていません"
                    ),
                )
            )
    return findings


def check(repo_root: Path) -> list[Finding]:
    """portable source の model id 混入と projection の配布所有を検証する。"""
    table = _load_table(repo_root)
    if table is None:
        return []
    return _portable_findings(repo_root, _model_ids(table)) + _socket_findings(repo_root, table)


__all__ = ["check"]
