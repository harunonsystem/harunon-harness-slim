"""テストパッケージ。

rigor profile (ADR-009) のゲートを持つ hook は 12 個あり、profile が casual
だと先頭で exit 0 して本体ロジックに入らない。profile は既定で実行マシンの
`~/.claude/rigor-patterns.json` から解決されるため、固定しないと gate 系の
assert が「テストを回したマシンの設定」次第で通ったり落ちたりする。
harunon-harness 自身は casual 指定なので、実際に 6 件が環境依存で落ちていた。

ここで `rigor-profile.sh` が公開しているテスト注入点を repo 内の fixture に
向け、suite 全体を rigorous に固定する。profile 判定そのものを検証する
`test_rigor_profile.py` は subprocess ごとに env を上書きするため影響しない。
"""
import os
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

os.environ["RIGOR_PATTERNS_FILE"] = str(_FIXTURES / "rigor-patterns.json")
os.environ["RIGOR_LOCAL_FILE"] = str(_FIXTURES / "rigor.local.json")
