#!/usr/bin/env python3
"""機械的に検査できる日本語技術文書の最低限のゲート。"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path


def _pr_body_patterns() -> list[list[str]]:
    # Claude/repo-local と shared-skills を使う runtime で同じ skill 本文を読む。
    local = Path(__file__).resolve().parent.parent / "skills/slop-word-refactor/SKILL.md"
    skill = local if local.is_file() else Path.home() / ".agents/skills/slop-word-refactor/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    match = re.search(r"<!-- pr-body-patterns -->\s*```json\n(.*?)\n```", text, flags=re.DOTALL)
    if not match:
        raise ValueError("slop-word-refactor の PR 本文規則を読めません")
    return json.loads(match[1])


# 公開 gate（pr-action.js の SIMPLE_WRAPPERS / WRAPPER_OPTIONS_WITH_VALUES / SHELL_COMMAND_WRAPPERS）と
# 同じ command 位置を見る。ずれると `env ... gh pr create` が gate には本文付きで届き、ここだけ素通りした
# （2026-11-04）。一致は scripts/tests/fixtures/pr-body-commands.json を両実装に通して固定する。
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SIMPLE_WRAPPERS = {
    "!", "builtin", "command", "declare", "do", "elif", "else", "env", "exec", "export", "if",
    "local", "nice", "nohup", "readonly", "sudo", "then", "time", "typeset", "until", "while",
}
_WRAPPER_VALUE_OPTIONS = {"env": {"-C", "--chdir", "-u", "--unset"}, "nice": {"-n", "--adjustment"},
                          "sudo": {"-C", "-u", "--user"}}
_SHELL_WRAPPERS = {"bash", "sh", "zsh", "dash", "ksh"}
_PR_BODY_TEXT = re.compile(r"\bgh\b[\s\S]*\bpr\s+(?:create|edit)\b")
_UNRESOLVED_PR = "PR コマンドの位置を確定できません（未知の wrapper / shell option）。単独の gh pr コマンドで実行してください"


def _hides_pr_body(segment: list[str]) -> bool:
    """直接の gh pr として読めなかった segment に PR 本文の変更が見えるか（pr-action.js hidesPrMutation と同じ）。"""
    if _command_words(segment)[:1] in (["echo"], ["printf"]):
        return False
    # /usr/bin/gh 等のパス指定も gh。gh の後ろの pr はすべて見る
    gh = next((i for i, token in enumerate(segment) if token.lstrip("\\").rsplit("/", 1)[-1] == "gh"), None)
    if gh is not None and any(token == "pr" and segment[i + 1:i + 2] in (["create"], ["edit"])
                              for i, token in enumerate(segment) if i > gh):
        return True
    words = _command_words(segment)
    return bool(words) and words[0] in _SHELL_WRAPPERS and any(_PR_BODY_TEXT.search(word) for word in words[1:])


def _command_words(segment: list[str]) -> list[str]:
    """env 代入と単純 wrapper（とその option）を飛ばした command 以降の語。"""
    index = 0
    while index < len(segment):
        token = segment[index]
        if _ENV_ASSIGNMENT.match(token):
            index += 1
            continue
        if token not in _SIMPLE_WRAPPERS:
            break
        values = _WRAPPER_VALUE_OPTIONS.get(token, set())
        index += 1
        while index < len(segment):
            option = segment[index]
            if _ENV_ASSIGNMENT.match(option):
                index += 1
                continue
            if option == "--":
                index += 1
                break
            if not option.startswith("-"):
                break
            index += 1
            if option.split("=", 1)[0] in values and "=" not in option:
                index += 1
    return segment[index:]


def _shell_script(args: list[str]) -> str | None:
    """`bash -c SCRIPT` の SCRIPT。-c を含む option の直後の語。"""
    for index, token in enumerate(args):
        if token == "--" or not token.startswith("-"):
            return None
        if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token):
            script = args[index + 1] if index + 1 < len(args) else None
            # `-c --` / `-c -e` は bash が後ろの語を script にする。確定できないので返さない
            return None if script is None or script.startswith("-") else script
    return None


def _body_from_command(command: str, wrapped: bool = False) -> tuple[str | None, str | None]:
    """wrapped: bash -c の script など、wrapper の内側で解析している（相対の本文ファイルは読めない）。"""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as exc:
        # PR 本文の更新でなければ検査対象外。前段の絞り込みは `gh` の有無しか見ていない。
        if not re.search(r"\bgh\s+pr\s+(?:create|edit)\b", command):
            return None, None
        return None, f"PR コマンドを解析できません: {exc}"

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(char in ";&|()\n" for char in token):
            segments.append([])
        else:
            segments[-1].append(token)

    body_option: tuple[bool, str] | None = None
    for raw_segment in segments:
        segment = _command_words(raw_segment)
        if segment[:1] and segment[0] in _SHELL_WRAPPERS:
            script = _shell_script(segment[1:])
            if script is None:
                if _hides_pr_body(raw_segment):
                    return None, _UNRESOLVED_PR
                continue
            body, error = _body_from_command(script, wrapped=True)
            if error is None and body is not None and len(segments) > 1:
                return None, "複合コマンドのPR本文更新は検査できません。更新を単独の gh pr コマンドに分けてください"
            if error is not None or body is not None:
                return body, error
            continue
        if segment[:2] == ["rtk", "gh"]:
            segment = segment[1:]
        if segment[:2] != ["gh", "pr"]:
            if _hides_pr_body(raw_segment):
                return None, _UNRESOLVED_PR
            continue
        if segment[2:3] not in (["create"], ["edit"]):
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
        skipped = raw_segment[:len(raw_segment) - len(segment)]
        wrapped = wrapped or any(not _ENV_ASSIGNMENT.match(token) for token in skipped if token != "rtk")

    if body_option is None:
        return None, None
    is_file, value = body_option
    # wrapper（env -C、sudo -D、bash -c 内の cd 等）は cwd を変え得る。option の綴りを追わず、
    # 直接の gh pr 以外では絶対パスを求める（pr-action.js publicationInput と同じ）
    if is_file and not value.startswith("/") and value not in {"-", "/dev/stdin"} and wrapped:
        return None, "wrapper（env / sudo / bash -c 等）経由の gh では本文ファイルを絶対パスで指定してください"
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
    for pattern, label in _pr_body_patterns():
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
    try:
        found = violations(body)
    except (OSError, ValueError) as exc:
        print(f"日本語技術文書ゲート: 推敲 skill の読込失敗: {exc}", file=sys.stderr)
        return 2
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
