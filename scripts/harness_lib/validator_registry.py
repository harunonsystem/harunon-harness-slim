"""harness_lib.validator_registry — validator の共通型。

check_* は repo_root -> list[Finding] の純関数（消費者は個別の順序や登録機構を
知る必要がない）。登録・実行順は harness_lib.validators.CHECKS が単独で持つ
（旧 ValidatorRegistry クラスは dict + for-loop の薄いラッパーで、消費者が
validators/__init__.py 1 箇所だけだったため削除し、その場に inline した）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Finding:
    """検証結果の 1 件。validate-harness / capability / policy 共通の不変値。

    check/level/message は必須。code/target/dimension/probe は
    構造化された詳細 (capability contract や live probe 由来) のみ設定する。
    """

    check: str
    level: str  # "error" | "warn"
    message: str
    code: str | None = None
    target: str | None = None
    dimension: str | None = None
    probe: str | None = None


ValidatorFn = Callable[[Path], list[Finding]]


__all__ = ["Finding", "ValidatorFn"]
