#!/usr/bin/env python3
"""機械的に検査できる日本語技術文書の最低限のゲート。"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path


# Skill のうち、文脈に依存せず機械的に検出できる空句だけを対象にする。
FORBIDDEN_PATTERNS = (
    (r"重要なのは", "予告の空句"),
    (r"本章では", "章の予告"),
    (r"ここでは.{0,24}(見ていく|扱う|探求する)", "内容の予告"),
    (r"(?:まとめると|要するに)", "直前の総括"),
    (r"正面から(?:扱う|回収する|見る|書く|立てる)", "姿勢の宣言"),
    (r"(?:深掘り|掘り下げ)する", "内容のない動詞"),
    (r"言語化する", "内容のない動詞"),
)


def _body_from_command(command: str) -> tuple[str | None, str | None]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as exc:
        return None, f"PR コマンドを解析できません: {exc}"

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(char in ";&|()\n" for char in token):
            segments.append([])
        else:
            segments[-1].append(token)

    body_option: tuple[bool, str] | None = None
    for segment in segments:
        while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
            segment = segment[1:]
        if segment[:2] == ["rtk", "gh"]:
            segment = segment[1:]
        if segment[:2] != ["gh", "pr"] or segment[2:3] not in (["create"], ["edit"]):
            continue
        if segment[3:] in (["--help"], ["-h"]):
            continue
        args = iter(segment[3:])
        options: list[tuple[bool, str]] = []
        for token in args:
            if token in {"--body", "-b", "--body-file", "-F"}:
                value = next(args, None)
                if value is None:
                    return None, f"{token} の値がありません"
                options.append((token in {"--body-file", "-F"}, value))
            elif token.startswith(("--body=", "--body-file=")):
                flag, value = token.split("=", 1)
                options.append((flag == "--body-file", value))
            elif token.startswith(("-b", "-F")):
                options.append((token.startswith("-F"), token[2:].removeprefix("=")))
        if len(options) > 1:
            return None, "PR本文の指定が重複しています。本文オプションを1つだけ指定してください"
        if not options and segment[2] == "edit":
            continue
        # ponytail: arbitrary shell execution is not modeled; split mutations into literal commands.
        if len(segments) > 1:
            return None, "複合コマンドのPR本文更新は検査できません。更新を単独の gh pr コマンドに分けてください"
        if not options:
            return None, "PR本文をコマンドから取得できません（--body または --body-file が必要です）"
        body_option = options[0]

    if body_option is None:
        return None, None
    is_file, value = body_option
    if "$" in value or "`" in value:
        return None, "動的なPR本文は検査できません。確定した本文ファイルを指定してください"
    if not is_file:
        return value, None
    if value in {"-", "/dev/stdin"}:
        return None, "標準入力のPR本文は検査できません"
    try:
        return Path(value).read_text(encoding="utf-8"), None
    except (OSError, UnicodeError):
        return None, "PR本文ファイルをUTF-8で読めません"


def violations(text: str) -> list[str]:
    # コード例の中の日本語まで文体違反として扱わない。
    prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    found: list[str] = []
    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, prose):
            found.append(label)
    return found


def check_command(command: str) -> int:
    body, error = _body_from_command(command)
    if error:
        print(f"日本語技術文書ゲート: {error}", file=sys.stderr)
        return 2
    if body is None:
        return 0
    if not body.strip():
        print("日本語技術文書ゲート: PR本文が空です", file=sys.stderr)
        return 2
    found = violations(body)
    if found:
        print("日本語技術文書ゲート: PR本文に禁止表現があります: " + ", ".join(found), file=sys.stderr)
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check-command"])
    parser.add_argument("command")
    args = parser.parse_args()
    return check_command(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
