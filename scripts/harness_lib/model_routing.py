"""harness_lib.model_routing — model routing SSOT table の検証と投影。

packages/core/model-routing.json は ADR-010 の役割別モデル割当を機械可読に
した台帳。各 runtime の宣言ファイル（codex の toml / pi の settings.json と agents
frontmatter / opencode の agents frontmatter / omp の config.yml modelRoles）は
この表の投影（生成物）であり、danger-rules.json の autoMode → settings.json と
同じ「table が SSOT、宣言ファイルは生成物、validator が一致を強制」型で扱う。

公開する操作は 3 つ:
  - check(repo_root)      validate-harness の check（schema + cross-field + 投影一致）
  - drifts(table, repo)   投影先と table の不一致を文字列で列挙（sync 前の --check）
  - apply(table, repo)    投影先の該当行の値だけを差し替える（他の整形は保持）
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .frontmatter import frontmatter_block
from .jsonio import load_json_object
from .policy_kernel import TableSpec, check_table
from .schema import validate as validate_schema

TABLE_PATH = "packages/core/model-routing.json"
_SCHEMA_PATH = "schemas/model-routing.schema.json"
SYNC_SCRIPT = "scripts/sync-model-routing.py"


def load(repo_root: Path) -> dict:
    return load_json_object(repo_root / TABLE_PATH)


# -- validate ----------------------------------------------------------------


def _schema_errors(table: dict, repo_root: Path) -> list[str]:
    schema_path = repo_root / _SCHEMA_PATH
    if not schema_path.is_file():
        raise FileNotFoundError(f"schema file not found: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return [f"schema: {e}" for e in validate_schema(table, schema)]


def _validate_table(table: dict, repo_root: Path) -> list[str]:
    """構造は JSON Schema、ここは schema で書けない cross-field 制約だけを見る。

    - (runtime, role) の重複禁止
    - model は models の alias であること（defaults / route 両方）
    - defaults[purpose] から model / effort が逸脱する route は reason 必須、
      逸脱しない route に reason を書くことは禁止（stale な理由文を残さない）
    - format ごとの projection 制約: frontmatter / omp-roles は provider 必須、
      omp-roles は effortKeys 空（値に thinking が同居する）、providerKey は json のみ
    - projection.path は route.runtime の target ディレクトリ配下（packages/targets/<runtime>/）
    - key の形が format と一致すること（reader と renderer が同じ行を指す前提）:
      omp-roles は `modelRoles.<role>`、frontmatter は dot 無しのトップレベル名、
      toml / json は dotted 名（各セグメントは識別子）
    - 書き込み先 (path, key) は table 全体で一意（2 route が同じ行を書かない）
    """
    errors = _schema_errors(table, repo_root)
    if errors:
        return errors

    models = table["models"]
    defaults = table["defaults"]
    for purpose, assignment in defaults.items():
        if assignment["model"] not in models:
            errors.append(f"defaults.{purpose}: model alias {assignment['model']!r} は models に無い")

    seen: set[tuple[str, str]] = set()
    write_targets: dict[tuple[str, str], str] = {}
    for route in table["routes"]:
        label = f"{route['runtime']}/{route['role']}"
        key = (route["runtime"], route["role"])
        if key in seen:
            errors.append(f"routes[{label}]: (runtime, role) が重複している")
        seen.add(key)

        if route["model"] not in models:
            errors.append(f"routes[{label}]: model alias {route['model']!r} は models に無い")

        default = defaults[route["purpose"]]
        deviates = (route["model"], route["effort"]) != (default["model"], default["effort"])
        if deviates and "reason" not in route:
            errors.append(
                f"routes[{label}]: purpose={route['purpose']} の既定"
                f"（{default['model']} {default['effort']}）から逸脱しているのに reason が無い"
            )
        if not deviates and "reason" in route:
            errors.append(f"routes[{label}]: 既定どおりの route に reason を書かない（逸脱にだけ理由を残す）")

        for projection in route["projections"]:
            fmt = projection["format"]
            plabel = f"routes[{label}].projections[{projection['path']}]"
            if fmt in ("frontmatter", "omp-roles") and "provider" not in projection:
                errors.append(f"{plabel}: format={fmt} は provider が必須")
            if fmt == "omp-roles" and projection["effortKeys"]:
                errors.append(f"{plabel}: format=omp-roles は値に thinking が同居するため effortKeys は空にする")
            if "providerKey" in projection and fmt != "json":
                errors.append(f"{plabel}: providerKey は json 投影だけが持てる")
            if "providerKey" in projection and "provider" not in projection:
                errors.append(f"{plabel}: providerKey を持つなら provider も必須")

            expected_prefix = f"packages/targets/{route['runtime']}/"
            if not projection["path"].startswith(expected_prefix):
                errors.append(f"{plabel}: path は runtime={route['runtime']} の {expected_prefix} 配下でなければならない")

            keys = [projection["modelKey"], *projection["effortKeys"]]
            if "providerKey" in projection:
                keys.append(projection["providerKey"])
            for key in keys:
                shape_error = _key_shape_error(fmt, key)
                if shape_error:
                    errors.append(f"{plabel}: key {key!r} は {shape_error}")
                target = (projection["path"], key)
                if target in write_targets:
                    errors.append(
                        f"{plabel}: {key} は routes[{write_targets[target]}] も書く（同じ (path, key) を 2 route が投影している）"
                    )
                write_targets.setdefault(target, label)
    return errors


_IDENT = r"[A-Za-z0-9_-]+"
_DOTTED_KEY_RE = re.compile(rf"^{_IDENT}(\.{_IDENT})*$")
_TOP_LEVEL_KEY_RE = re.compile(rf"^{_IDENT}$")
_OMP_ROLE_KEY_RE = re.compile(rf"^modelRoles\.{_IDENT}$")


def _key_shape_error(fmt: str, key: str) -> str | None:
    """format ごとの key の形（reader の dotted 解決と renderer の行特定が同じ行を指す前提）。"""
    if fmt == "omp-roles":
        return None if _OMP_ROLE_KEY_RE.match(key) else "format=omp-roles では modelRoles.<role> の形"
    if fmt == "frontmatter":
        return None if _TOP_LEVEL_KEY_RE.match(key) else "format=frontmatter では dot 無しのトップレベル名"
    return None if _DOTTED_KEY_RE.match(key) else f"format={fmt} では識別子を . で繋いだ dotted 名"


# -- projection --------------------------------------------------------------


def expected_values(table: dict, route: dict, projection: dict) -> dict[str, str]:
    """1 projection が宣言ファイルに書くべき key -> 値（文字列）。

    format が model の描き方を決める: toml / json は bare id、frontmatter は
    provider/model、omp-roles は provider/model:effort。
    """
    model_id = table["models"][route["model"]]
    effort = route["effort"]
    fmt = projection["format"]
    if fmt in ("toml", "json"):
        model_value = model_id
    elif fmt == "frontmatter":
        model_value = f"{projection['provider']}/{model_id}"
    elif fmt == "omp-roles":
        model_value = f"{projection['provider']}/{model_id}:{effort}"
    else:
        raise ValueError(f"unknown projection format: {fmt}")

    values = {projection["modelKey"]: model_value}
    for key in projection["effortKeys"]:
        values[key] = effort
    if "providerKey" in projection:
        values[projection["providerKey"]] = projection["provider"]
    return values


def _dotted(data: object, key: str) -> object:
    for part in key.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _parse(text: str, fmt: str) -> dict:
    if fmt == "toml":
        return tomllib.loads(text)
    if fmt == "json":
        return json.loads(text)
    import yaml  # yaml を扱う投影（omp / frontmatter）だけが PyYAML を要求する

    if fmt == "omp-roles":
        return yaml.safe_load(text)
    match = frontmatter_block(text)
    if match is None:
        raise ValueError("frontmatter ブロックが無い")
    return yaml.safe_load(match.group(1)) or {}


def actual_values(text: str, projection: dict) -> dict[str, object]:
    """宣言ファイルの現在値を expected_values と同じ key で返す（欠落は None）。"""
    data = _parse(text, projection["format"])
    keys = [projection["modelKey"], *projection["effortKeys"]]
    if "providerKey" in projection:
        keys.append(projection["providerKey"])
    return {key: _dotted(data, key) for key in keys}


def _route_projections(table: dict):
    for route in table["routes"]:
        for projection in route["projections"]:
            yield route, projection


def drifts(table: dict, repo_root: Path) -> list[str]:
    """投影先が table と一致しない箇所を列挙する（空 = 一致）。"""
    errors: list[str] = []
    for route, projection in _route_projections(table):
        label = f"{route['runtime']}/{route['role']}"
        path = repo_root / projection["path"]
        if not path.is_file():
            errors.append(f"projection[{label}]: {projection['path']} が無い")
            continue
        text = path.read_text(encoding="utf-8")
        try:
            actual = actual_values(text, projection)
        except ValueError as error:
            errors.append(f"projection[{label}]: {projection['path']}: {error}")
            continue
        for key, expected in expected_values(table, route, projection).items():
            if actual[key] != expected:
                errors.append(
                    f"projection[{label}]: {projection['path']} の {key} が table と一致しません"
                    f"（actual={actual[key]!r}, expected={expected!r}）。{SYNC_SCRIPT} を実行してください"
                )
    return errors


def _projection_model_id(value: object, projection: dict) -> str | None:
    """projection の表現から provider を除いた model id を返す。"""
    if not isinstance(value, str) or not value:
        return None
    fmt = projection["format"]
    if fmt in ("toml", "json"):
        return value
    provider = projection.get("provider")
    if not isinstance(provider, str):
        return None
    prefix = f"{provider}/"
    if not value.startswith(prefix):
        return value
    model_id = value[len(prefix):]
    if fmt == "omp-roles":
        model_id, separator, _ = model_id.rpartition(":")
        if not separator:
            return None
    return model_id or None


def _check_no_foreign_models(table: dict, repo_root: Path) -> list[str]:
    """projection の model key が table の models 以外を指さないこと。"""
    known = set(table["models"].values())
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for _, projection in _route_projections(table):
        rel = projection["path"]
        path = repo_root / rel
        if not path.is_file():
            continue  # 欠落は drifts が報告する
        try:
            actual = actual_values(path.read_text(encoding="utf-8"), projection)
        except ValueError:
            continue  # 形式不正は drifts が報告する
        model_id = _projection_model_id(actual.get(projection["modelKey"]), projection)
        if model_id is None or model_id in known:
            continue
        marker = (rel, projection["modelKey"], model_id)
        if marker in seen:
            continue
        seen.add(marker)
        errors.append(
            f"foreign-model: {rel} の {projection['modelKey']} に "
            f"table の models に無い model id がある: {model_id}"
        )
    return errors


# -- apply ---------------------------------------------------------------------


def _replace_once(text: str, pattern: re.Pattern, value: str, where: str) -> str:
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"{where}: 差し替え対象の行が {len(matches)} 件（1 件でなければならない）")
    match = matches[0]
    return text[: match.start(1)] + value + text[match.end(1) :]


def _replace_toml(text: str, key: str, value: str, where: str) -> str:
    # dotted key の末尾セグメントだけで行を特定する（[agents] 等の table 内でも
    # key 名がファイル内で一意であることを 1 件一致で保証する）
    name = key.split(".")[-1]
    pattern = re.compile(rf'^{re.escape(name)}\s*=\s*"([^"]*)"', re.MULTILINE)
    return _replace_once(text, pattern, value, f"{where}:{key}")


def _replace_json(text: str, key: str, value: str, where: str) -> str:
    # toml と同じく dotted key の末尾セグメントで行を特定し、1 件一致で一意性を保証する
    name = key.split(".")[-1]
    pattern = re.compile(rf'^\s*"{re.escape(name)}"\s*:\s*"([^"]*)"', re.MULTILINE)
    return _replace_once(text, pattern, value, f"{where}:{key}")


def _replace_in_span(text: str, span: tuple[int, int], key: str, value: str, where: str) -> str:
    start, end = span
    pattern = re.compile(rf"^[ \t]*{re.escape(key)}:[ \t]*(\S[^\n]*)$", re.MULTILINE)
    replaced = _replace_once(text[start:end], pattern, value, f"{where}:{key}")
    return text[:start] + replaced + text[end:]


def _frontmatter_span(text: str, where: str) -> tuple[int, int]:
    match = frontmatter_block(text)
    if match is None:
        raise ValueError(f"{where}: frontmatter ブロックが無い")
    return match.span(1)


def _omp_roles_span(text: str, where: str) -> tuple[int, int]:
    match = re.search(r"^modelRoles:\n((?:[ \t]+[^\n]*\n)+)", text, re.MULTILINE)
    if match is None:
        raise ValueError(f"{where}: modelRoles ブロックが無い")
    return match.span(1)


def render(text: str, projection: dict, values: dict[str, str]) -> str:
    """宣言ファイルのテキストに values を書き込んだ結果を返す（該当行の値だけを差し替える）。"""
    fmt = projection["format"]
    where = projection["path"]
    for key, value in values.items():
        if fmt == "toml":
            text = _replace_toml(text, key, value, where)
        elif fmt == "json":
            text = _replace_json(text, key, value, where)
        elif fmt == "frontmatter":
            text = _replace_in_span(text, _frontmatter_span(text, where), key, value, where)
        elif fmt == "omp-roles":
            role = key.split(".")[-1]
            text = _replace_in_span(text, _omp_roles_span(text, where), role, value, where)
        else:
            raise ValueError(f"unknown projection format: {fmt}")
    return text


def apply(table: dict, repo_root: Path) -> list[Path]:
    """全 projection を書き込み、内容が変わったファイルを返す。

    全ファイルの render を先に済ませ、1 つでも失敗（該当行が無い / 曖昧）したら
    何も書かない。途中で例外が出て一部だけ更新された状態を残さないため。
    同じファイルへの複数 projection（codex config.toml / omp config.yml）は
    メモリ上のテキストへ順に適用する。
    """
    originals: dict[Path, str] = {}
    rendered: dict[Path, str] = {}
    for route, projection in _route_projections(table):
        path = repo_root / projection["path"]
        if path not in originals:
            originals[path] = path.read_text(encoding="utf-8")
            rendered[path] = originals[path]
        rendered[path] = render(rendered[path], projection, expected_values(table, route, projection))

    changed: list[Path] = []
    for path, text in rendered.items():
        if text != originals[path]:
            path.write_text(text, encoding="utf-8")
            changed.append(path)
    return changed


# -- validate-harness check --------------------------------------------------

_ROUTING_SPEC = TableSpec(
    name="model-routing",
    table_rel=TABLE_PATH,
    validate=_validate_table,
    checks=[drifts, _check_no_foreign_models],
)


def check(repo_root: Path):
    """model-routing.json と各 runtime の宣言ファイルの一致を検証する（Policy Kernel へ委譲）。"""
    return check_table(repo_root, _ROUTING_SPEC)


__all__ = [
    "SYNC_SCRIPT",
    "TABLE_PATH",
    "actual_values",
    "apply",
    "check",
    "drifts",
    "expected_values",
    "load",
    "render",
]
