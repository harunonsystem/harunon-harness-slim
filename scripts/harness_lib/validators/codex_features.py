"""computedFeatures の feature table と、実際に配布する config.toml の整合を検証する。

settingsSync の keys / removeKeys は feature table（declare フラグ）から導出されるため、
table と config.toml がずれると「宣言したのに書かれていない」「撤去するはずが残っている」
が静かに成立する。ここで両者を突き合わせる。

codex 側の実測 default（table の default / stage）が現行 CLI と合っているかは、codex CLI
が要るのでここでは見ない（CI に codex は無い）。harness-doctor.sh が担当する。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from ..jsonio import JsonLoadError, load_json_object
from ..schema import validate as validate_schema
from ..validator_registry import Finding
from ._common import target_configs

CHECK = "codex-features"


def _finding(message: str, level: str = "error") -> Finding:
    return Finding(check=CHECK, level=level, message=message)


def _table_findings(repo_root: Path, table_rel: str) -> tuple[dict | None, list[Finding]]:
    """feature table を読み、schema 検証の結果を返す。読めなければ (None, findings)。"""
    table_path = repo_root / table_rel
    if not table_path.is_file():
        return None, [_finding(f"{table_rel}: computedFeatures.table が存在しません")]
    try:
        table = load_json_object(table_path)
    except JsonLoadError as error:
        return None, [_finding(f"{table_rel}: {error.reason}")]

    schema_path = repo_root / "schemas" / "codex-features.schema.json"
    if not schema_path.is_file():
        return table, []
    return table, [
        _finding(f"{table_rel}: {err}") for err in validate_schema(table, load_json_object(schema_path))
    ]


def _declared_findings(name: str, entry: dict, written, table_rel: str, source_rel: str) -> list[Finding]:
    """declare true の 1 件について、config.toml の書かれ方が table と一致するか見る。"""
    if written is None:
        return [_finding(
            f"{table_rel}: {name} は declare true ですが {source_rel} の [features] にありません"
        )]

    shape = entry["shape"]
    if shape == "bool":
        if not isinstance(written, bool):
            return [_finding(
                f"{source_rel}: features.{name} は shape bool の宣言ですが table で書かれています"
            )]
        return []

    if not isinstance(written, dict):
        return [_finding(
            f"{source_rel}: features.{name} は shape table の宣言ですが bool で書かれています"
            "（codex 側の既定値に戻ります）"
        )]
    expected = set(entry["fields"])
    actual = set(written)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        detail = ", ".join(
            part for part in (
                f"未記載: {', '.join(missing)}" if missing else "",
                f"table に無いキー: {', '.join(unknown)}" if unknown else "",
            ) if part
        )
        return [_finding(f"{source_rel}: features.{name} の fields が table と不一致（{detail}）")]
    return []


def check_codex_features(repo_root: Path) -> list[Finding]:
    """computedFeatures 宣言を持つ target について、feature table と config.toml を突き合わせる。"""
    configs, findings = target_configs(repo_root, CHECK)
    for _config_path, cfg in configs:
        spec = (cfg.get("settingsSync") or {}).get("computedFeatures")
        if not spec:
            continue
        table_rel = spec["table"]
        table, table_findings = _table_findings(repo_root, table_rel)
        findings += table_findings
        if table is None:
            continue

        source_rel = cfg["settingsSync"]["source"]
        source_path = repo_root / source_rel
        if not source_path.is_file():
            findings.append(_finding(f"{source_rel}: settingsSync.source が存在しません"))
            continue
        written_features = tomllib.loads(source_path.read_text(encoding="utf-8")).get(
            spec["prefix"], {}
        )

        for name, entry in table["features"].items():
            written = written_features.get(name)
            if entry["declare"]:
                findings += _declared_findings(name, entry, written, table_rel, source_rel)
            elif written is not None:
                findings.append(_finding(
                    f"{source_rel}: features.{name} は declare false（{entry['why']}）ですが書かれています"
                ))

        undeclared = sorted(set(written_features) - set(table["features"]))
        for name in undeclared:
            findings.append(_finding(
                f"{table_rel}: {source_rel} の features.{name} が table にありません"
                "（declare の判断と撤去宣言が漏れます）"
            ))
    return findings


CHECKS = {"codex-features": check_codex_features}
