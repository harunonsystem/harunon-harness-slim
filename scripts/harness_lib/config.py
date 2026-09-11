"""harness_lib.config — target config の読み込みユーティリティ。"""
from __future__ import annotations

import os
from pathlib import Path

from .jsonio import JsonLoadError, load_json_object
from .schema import validate as validate_schema


def repo_root() -> Path:
    """リポジトリルートを返す。

    このファイルは scripts/harness_lib/config.py にあるため、
    2 段上がるとリポジトリルートに到達する。
    """
    return Path(__file__).resolve().parent.parent.parent


def target_config_errors(config_path: Path, root: Path) -> list[str]:
    """target config の schema 構造を検証し、エラーを返す。

    schema は必須の契約として扱い、load_target と validator が同じ検証結果を
    共有する。
    """
    schema_path = root / "schemas" / "target-config.schema.json"
    if not schema_path.is_file():
        raise FileNotFoundError(f"schema file not found: {schema_path}")

    data = load_json_object(config_path)
    schema = load_json_object(schema_path)
    return validate_schema(data, schema)


def target_config_paths(root: Path) -> list[Path]:
    """packages/targets/*/config.json を安定順で返す（唯一の target 列挙）。

    validator / distribution / bootstrap が各自 `iterdir()` / `glob()` で列挙すると
    ディレクトリ不在時の挙動（crash か空か）と順序がずれる。ここに一本化する。
    packages/targets が無ければ空。
    """
    targets_dir = root / "packages" / "targets"
    if not targets_dir.is_dir():
        return []
    return sorted(targets_dir.glob("*/config.json"))


def target_names(
    root: Path,
    *,
    include_auxiliary: bool = False,
    require_instructions: bool = False,
) -> list[str]:
    """packages/targets の有効な target 名を安定順で返す。"""
    names: list[str] = []
    for config_path in target_config_paths(root):
        name = config_path.parent.name
        try:
            cfg = load_target(name, root)
        except (OSError, ValueError):
            continue
        if not include_auxiliary and cfg.get("auxiliary") is True:
            continue
        if require_instructions and not str(cfg.get("instructionsFile", "")).strip():
            continue
        configured_name = cfg.get("name", name)
        if isinstance(configured_name, str) and configured_name:
            names.append(configured_name)
    return sorted(set(names))


def load_target(name: str, root: Path) -> dict:
    """packages/targets/<name>/config.json を読み込み dict を返す。

    configDir に宣言された環境変数があればそれを優先し、~ は展開して返す。
    """
    config_path = root / "packages" / "targets" / name / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"config.json が見つかりません: {config_path}")
    errors = target_config_errors(config_path, root)
    if errors:
        raise ValueError(
            f"target config が不正です: {config_path}: " + "; ".join(errors)
        )
    cfg = load_json_object(config_path)
    if cfg.get("name") != name:
        raise ValueError(
            f"target config の name がディレクトリ名と一致しません: "
            f"{cfg.get('name')!r} != {name!r}"
        )

    if "configDir" in cfg:
        config_dir = cfg["configDir"]
        env_name = cfg.get("configDirEnv")
        if env_name:
            env_value = os.environ.get(env_name)
            if env_value:
                override = Path(env_value).expanduser()
                if not override.is_absolute():
                    raise ValueError(f"{env_name} must be an absolute path")
                config_dir = str(override)
        expanded = str(Path(config_dir).expanduser())
        cfg = dict(cfg)
        cfg["configDir"] = expanded

    return cfg
