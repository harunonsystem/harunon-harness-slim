#!/usr/bin/env python3
"""danger-rules.json（危険コマンドルール SSOT）から claude settings.json の
autoMode（hard_deny/soft_deny）を再生成する。

autoMode は Claude Code の auto-mode classifier が読む自然文プロース配列で、
これまで settings.json 側に手書きされていた。危険コマンドの判断基準は
packages/core/policy/danger-rules.json が SSOT であり、そこに rule ごとの
autoMode 投影（hard_deny/soft_deny のどちらに、どの日本語プロースで載るか）を
書けば settings.json 側は生成物として導出できる。二重管理（table を直しても
settings.json 側は手で直さないと drift する）を防ぐためにこのスクリプトを置く。

Usage:
    sync-auto-mode-rules.py           packages/core/settings.json を書き換える
    sync-auto-mode-rules.py --check   drift のみ検出（exit 1 なら不一致、書き込まない）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib.runtime import require_supported_python  # noqa: E402

require_supported_python()

from harness_lib import danger_rules  # noqa: E402

_TABLE_PATH = "packages/core/policy/danger-rules.json"
_SETTINGS_PATH = "packages/core/settings.json"


def _derive(repo_root: Path) -> dict[str, list[str]]:
    """core + extras（会社・プロジェクト固有の追加ルールも autoMode を宣言できる）から投影値を導出する。"""
    table = json.loads((repo_root / _TABLE_PATH).read_text(encoding="utf-8"))
    rules = danger_rules.core_and_extra_rules(table, repo_root)
    return danger_rules.auto_mode_rules({"rules": rules})


def check(repo_root: Path) -> int:
    """settings.json の autoMode と derive 結果を比較する。差分があれば 1 を返す。"""
    settings_path = repo_root / _SETTINGS_PATH
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    expected = _derive(repo_root)
    actual = settings.get("autoMode", {})

    mismatched = False
    for tier, expected_list in expected.items():
        actual_list = actual.get(tier)
        if actual_list != expected_list:
            mismatched = True
            print(f"[{tier}] 不一致:")
            print(f"  settings.json: {actual_list}")
            print(f"  derived      : {expected_list}")

    if mismatched:
        print(
            "\nsettings.json の autoMode が danger-rules.json と食い違っています。"
            " scripts/sync-auto-mode-rules.py を実行してください。"
        )
        return 1
    print("OK: settings.json の autoMode は danger-rules.json と一致しています")
    return 0


def _find_top_level_value_span(text: str, key: str) -> tuple[int, int] | None:
    """トップレベル（4-space indent）の `"key": <value>` について value の文字範囲を返す。

    settings.json は他のキー（denyWrite 配列や credentials.files のインライン
    object 等）を人手で好みの折り返しにしているため、ファイル全体を
    json.dumps() で作り直すとそこまで巻き込んで整形が変わってしまう
    （実測: 意図した変更と無関係な 70 行超の diff が出た）。autoMode の
    value だけをテキストレベルで差し替えるため、json.JSONDecoder.raw_decode で
    「key の直後から始まる 1 個の JSON 値」の終端位置だけを求める（波括弧の
    深さを手で数えず、文字列中の `{`/`}` の誤検出も避けられる）。
    """
    match = re.search(r'^ {4}"' + re.escape(key) + r'":\s*', text, re.MULTILINE)
    if match is None:
        return None
    value_start = match.end()
    _, value_end = json.JSONDecoder().raw_decode(text, value_start)
    return value_start, value_end


def _render_nested_value(value: object) -> str:
    """value を json.dumps(indent=4) した上で、トップレベルキー1段分の追加インデントを足す。

    json.dumps は先頭行を column 0 前提で出力するため、1行目はそのまま
    （呼び出し側で `"autoMode": ` の直後に接続する）、2行目以降にだけ
    ファイルの1段（4 spaces）を足す。
    """
    dumped = json.dumps(value, ensure_ascii=False, indent=4)
    lines = dumped.splitlines()
    return "\n".join([lines[0]] + ["    " + line for line in lines[1:]])


def sync(repo_root: Path) -> int:
    """settings.json の autoMode を derive 結果で上書きする。他キー・他部分の整形は一切変えない。"""
    settings_path = repo_root / _SETTINGS_PATH
    text = settings_path.read_text(encoding="utf-8")
    settings = json.loads(text)
    expected = _derive(repo_root)

    if settings.get("autoMode") == expected:
        print("OK: 変更なし（既に一致しています）")
        return 0

    rendered = _render_nested_value(expected)
    existing_span = _find_top_level_value_span(text, "autoMode")
    if existing_span is not None:
        value_start, value_end = existing_span
        new_text = text[:value_start] + rendered + text[value_end:]
    else:
        # 初回導入時: 権限系の設定が並ぶ "permissions" の直後に新規キーとして挿入する。
        permissions_span = _find_top_level_value_span(text, "permissions")
        if permissions_span is None:
            raise SystemExit(f"{settings_path}: トップレベルキー 'permissions' が見つかりません")
        _, permissions_end = permissions_span
        comma_idx = text.index(",", permissions_end)
        insert_at = text.index("\n", comma_idx) + 1
        block = f'    "autoMode": {rendered},\n'
        new_text = text[:insert_at] + block + text[insert_at:]

    settings_path.write_text(new_text, encoding="utf-8")
    print(f"更新しました: {settings_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="drift 検出のみ（書き込まない）")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="リポジトリルート（デフォルト: スクリプトの親ディレクトリ）",
    )
    args = parser.parse_args()

    if args.check:
        return check(args.repo_root)
    return sync(args.repo_root)


if __name__ == "__main__":
    sys.exit(main())
