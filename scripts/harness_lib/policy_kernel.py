"""harness_lib.policy_kernel — 深いモジュール: Policy Kernel (#006 Wave3).

Table 策: `TableSpec` + `check_table` — danger-rules.json / hook-pipeline.json
の同型 SSOT→validate→materialize 照合をパラメトリック化する。

Design:
- Interface を小さく: check_table(repo, spec) の1関数
- Leverage: 7 表現照合 (danger) / 4 runtime 照合 (hook) を1 kernelで束ねる
- 情報隠蔽: table の load / validate / early-return / 各照合の逐次実行を隠蔽
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .jsonio import JsonLoadError, load_json_object
from .validator_registry import Finding


# -- Table 策 ---------------------------------------------------------------


@dataclass(frozen=True)
class TableSpec:
    """SSOT table 1件分の検証仕様."""

    name: str
    table_rel: str
    validate: Callable[[dict, Path], list[str]]
    # 各 check は (table, repo_root) -> list[str]。validate が通った後のみ実行
    checks: list[Callable[[dict, Path], list[str]]] = field(default_factory=list)


def check_table(repo_root: Path, spec: TableSpec) -> list[Finding]:
    """SSOT table を load→validate→checks の順で照合し、違反を Finding で返す.

    table 自体が存在しない場合は何も検証しない (導入前の repo との後方互換).
    table が JSON として壊れている / root がオブジェクトでない場合は traceback にせず
    Finding 1 件で報告し、validate / checks は実行しない (壊れた入力に対する照合は
    ノイズになるうえ、callback 側の `.get()` が AttributeError で落ちる).
    validate がエラーを返した場合は以降の checks は実行せず打ち切る
    (validate 前提が崩れた照合はノイズになるため).
    """
    table_path = repo_root / spec.table_rel
    if not table_path.is_file():
        return []
    try:
        table = load_json_object(table_path)
    except JsonLoadError as error:
        return _to_findings(spec, [f"table: {error.reason}"])
    errors = spec.validate(table, repo_root)
    if errors:
        return _to_findings(spec, errors)
    for fn in spec.checks:
        errors.extend(fn(table, repo_root))
    return _to_findings(spec, errors)


def _to_findings(spec: TableSpec, messages: list[str]) -> list[Finding]:
    return [Finding(check=spec.name, level="error", message=message) for message in messages]


__all__ = ["TableSpec", "check_table"]
