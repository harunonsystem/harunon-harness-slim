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
        tokens = shlex.split(command)
    except ValueError as exc:
        return None, f"PR コマンドを解析できません: {exc}"

    start = None
    for index, token in enumerate(tokens):
        if token == "gh":
            command_start = index
        elif token == "rtk" and index + 1 < len(tokens) and tokens[index + 1] == "gh":
            command_start = index + 1
        else:
            continue
        if tokens[command_start + 1 : command_start + 3] == ["pr", "create"]:
            start = command_start + 3
            break
    if start is None:
        return "", None

    args = tokens[start:]
    for index, token in enumerate(args):
        if token in {"--body", "-b", "--body-file"}:
            if index + 1 >= len(args):
                return None, f"{token} の値がありません"
            value = args[index + 1]
            if token == "--body-file":
                if value in {"-", "/dev/stdin"}:
                    return None, "標準入力のPR本文は検査できません"
                try:
                    return Path(value).read_text(encoding="utf-8"), None
                except OSError as exc:
                    return None, f"PR本文ファイルを読めません: {exc}"
            return value, None
        for prefix in ("--body=", "--body-file="):
            if token.startswith(prefix):
                value = token[len(prefix) :]
                if prefix == "--body-file=":
                    try:
                        return Path(value).read_text(encoding="utf-8"), None
                    except OSError as exc:
                        return None, f"PR本文ファイルを読めません: {exc}"
                return value, None

    return None, "PR本文をコマンドから取得できません（--body または --body-file が必要です）"


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
    assert body is not None
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
