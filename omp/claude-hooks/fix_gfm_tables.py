#!/usr/bin/env python3
"""GFM 形式でない Markdown テーブルを検出・修正するスクリプト。

対象はヘッダ行とセパレータ行が並んだ「テーブルブロック」だけ。パイプを含む 1 行を
単独でテーブルと見なすと、散文やリスト項目を 1 列テーブルに壊す（実際に
core-standards.md の箇条書きが `| - 完了報告の… |` に変形された）。判定に
セパレータ行を必須にし、インラインコード内のパイプは区切りとして数えない。

例:
  foo | bar | baz  →  | foo | bar | baz |
  --- | --- | ---  →  | --- | --- | --- |

触らないもの:
  コードフェンス内の行
  セパレータ行を伴わないパイプ入りの行（`a | b` を含む散文・リスト項目）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


INLINE_CODE = re.compile(r'`[^`]*`')


def strip_inline_code(text: str) -> str:
    """インラインコード span を落とす。`| Check |` のようなパイプは表の区切りではない。"""
    return INLINE_CODE.sub('', text)


def is_table_row(line: str) -> bool:
    """テーブルのセル行に見えるか。区切りの判定からインラインコードは除く。"""
    stripped = strip_inline_code(line.strip())
    return bool(stripped) and '|' in stripped


def is_separator_row(line: str) -> bool:
    """セパレータ行かどうかを判定"""
    stripped = line.strip()
    # パイプと-とスペースのみで構成される行
    return bool(re.match(r'^[\|\s\-:]+$', stripped)) and '-' in stripped


def fix_table_row(line: str) -> str:
    """テーブル行をGFM形式に修正"""
    stripped = line.strip()

    # すでに正しい形式（パイプで始まりパイプで終わる）
    if stripped.startswith('|') and stripped.endswith('|'):
        return line

    # セルを分割して再構成
    cells = [cell.strip() for cell in stripped.split('|')]

    # 先頭・末尾の空セルを除去（不正な分割結果）
    while cells and cells[0] == '':
        cells.pop(0)
    while cells and cells[-1] == '':
        cells.pop()

    if not cells:
        return line

    # GFM形式で再構成
    return '| ' + ' | '.join(cells) + ' |'


def fence_marker(line: str) -> str | None:
    """コードフェンスの開始/終了行ならマーカー文字列（``` or ~~~）を返す"""
    stripped = line.strip()
    for marker in ('```', '~~~'):
        if stripped.startswith(marker):
            return marker
    return None


def table_block_length(lines: list[str], start: int) -> int:
    """start から始まるテーブルブロックの行数。テーブルでなければ 0。

    GFM のテーブルはヘッダ行とセパレータ行の 2 行で始まる。この 2 行が揃っていることを
    必須にするのが誤変換を防ぐ要点で、揃っていなければ散文かリスト項目として触らない。
    """
    if start + 1 >= len(lines):
        return 0
    if not is_table_row(lines[start]) or not is_separator_row(lines[start + 1]):
        return 0

    length = 2
    for line in lines[start + 2:]:
        if not is_table_row(line):
            break
        length += 1
    return length


def fix_gfm_tables(content: str) -> str:
    """コンテンツ内のテーブルをGFM形式に修正（コードフェンス内は対象外）"""
    lines = content.split('\n')
    result: list[str] = []
    open_fence = None
    index = 0

    while index < len(lines):
        line = lines[index]

        # コードフェンス内はそのまま通す（開始と同じマーカーで閉じる）
        marker = fence_marker(line)
        if open_fence is not None:
            if marker == open_fence:
                open_fence = None
            result.append(line)
            index += 1
            continue
        if marker is not None:
            open_fence = marker
            result.append(line)
            index += 1
            continue

        length = table_block_length(lines, index)
        if length:
            result.extend(fix_table_row(lines[i]) for i in range(index, index + length))
            index += length
            continue

        result.append(line)
        index += 1

    return '\n'.join(result)


def main():
    if len(sys.argv) < 2:
        print("Usage: fix_gfm_tables.py <file_path>", file=sys.stderr)
        sys.exit(1)

    file_path = Path(sys.argv[1])

    if not file_path.exists():
        sys.exit(0)

    if not file_path.suffix.lower() == '.md':
        sys.exit(0)

    try:
        content = file_path.read_text(encoding='utf-8')
        fixed = fix_gfm_tables(content)

        if fixed != content:
            file_path.write_text(fixed, encoding='utf-8')
            print(f"✓ Fixed GFM tables: {file_path}", file=sys.stderr)
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
