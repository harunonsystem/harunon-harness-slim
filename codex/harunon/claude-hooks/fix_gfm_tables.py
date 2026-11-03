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


def table_cells(line: str) -> list[str]:
    """Split only unescaped pipes outside matching backtick spans."""
    text = line.strip()
    cells = []
    start = index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "`":
            end = index
            while end < len(text) and text[end] == "`":
                end += 1
            marker = text[index:end]
            close = re.search(r"(?<!`)" + re.escape(marker) + r"(?!`)", text[end:])
            if close:
                index = end + close.end()
                continue
            index = end
            continue
        if text[index] == "|":
            cells.append(text[start:index].strip())
            start = index + 1
        index += 1
    cells.append(text[start:].strip())
    if cells and cells[0] == "" and text.startswith("|"):
        cells.pop(0)
    if cells and cells[-1] == "" and text.endswith("|"):
        cells.pop()
    return cells


def is_table_row(line: str) -> bool:
    return not line.startswith("    ") and len(table_cells(line)) > 1


def is_separator_row(line: str) -> bool:
    cells = table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def fix_table_row(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("|") and stripped.endswith("|"):
        return line
    return "| " + " | ".join(table_cells(line)) + " |"


def fence_marker(line: str) -> str | None:
    """コードフェンスの開始/終了行ならマーカー文字列（``` or ~~~）を返す"""
    match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
    return match.group(1) if match else None


def table_block_length(lines: list[str], start: int) -> int:
    """start から始まるテーブルブロックの行数。テーブルでなければ 0。

    GFM のテーブルはヘッダ行とセパレータ行の 2 行で始まる。この 2 行が揃っていることを
    必須にするのが誤変換を防ぐ要点で、揃っていなければ散文かリスト項目として触らない。
    """
    if start + 1 >= len(lines):
        return 0
    if (not is_table_row(lines[start]) or not is_separator_row(lines[start + 1])
            or len(table_cells(lines[start])) != len(table_cells(lines[start + 1]))):
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
            if (marker and marker[0] == open_fence[0] and len(marker) >= len(open_fence)
                    and re.fullmatch(r" {0,3}" + re.escape(marker) + r"[ \t]*", line)):
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
