"""harness_lib.schema — schema_validator への唯一の import 経路。

scripts/ は package ではないため、`schema_validator` は sys.path 経由でしか
解決できない。各モジュールが try/except や sys.path 操作を個別に持つと
「どの経路で入ったか」が呼び出し元ごとに変わるので、ここに一本化する。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from schema_validator import validate  # noqa: E402

__all__ = ["validate"]
