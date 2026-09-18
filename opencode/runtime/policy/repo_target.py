#!/usr/bin/env python3
"""CMD 文字列 → 対象 repo を解決する唯一の実装（bash / python / JS 共通で叩く）。

背景: 承認フラグの KEY（repo root + branch + HEAD）は「push/PR 対象の repo」で
計算しなければならないが、CMD 内の `cd` / `git -C` / `--cwd` を見落とすと repo A
の承認で `git -C <repo-b> push` が通ってしまう（2026-07-26 に実測）。旧実装
（review-gate.sh の `_codex_review_resolve_cwd`）は解決不能時に無言で呼び出し元
cwd へフォールバックしており、この穴を塞げていなかった。

契約（fail-closed）:
- 解決できたら実在するディレクトリの絶対パスを返す。
- 解決できない（複数 repo にまたがる・シェル展開が残る・存在しないパス等）場合は
  `UnresolvableTarget` を投げる。**推測してフォールバックしない。**
- CMD に repo 切り替えの指定が無ければ `base`（呼び出し元の session cwd）をそのまま返す。

CLI は bash から stdin 経由で CMD を渡す（argv 長・quote 事故を避けるため）。
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path


class UnresolvableTarget(Exception):
    """CMD から対象 repo を一意に決定できないことを示す。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- --git-dir / --work-tree: work tree と git dir を分離できるため cd では
#     解決できない。推測せず unresolvable に倒す。 ---
_UNRESOLVABLE_GIT_OPTIONS = ("--git-dir", "--work-tree")
_UNRESOLVABLE_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# env 代入の前に立てる wrapper 語。`env GIT_DIR=/x git ...` / `sudo GIT_DIR=...` は
# 代入がコマンド起点に無くても実行時に効く。シェルの builtin/キーワード
# （export/declare/typeset/readonly/local, !, if/then/else/elif/do/while/until）も
# 透過にする — `export GIT_DIR=/x; git push` や `if true; then GIT_DIR=/x git push; fi`
# は export された環境が後続コマンドへ漏れるため resolvable に落ちてはならない
# （2026-08-29 レビューで検出。main の `(^|\s)` 正規表現だと未解決になっていた）。
_ENV_WRAPPERS = {
    "env",
    "command",
    "exec",
    "sudo",
    "nohup",
    "time",
    "nice",
    "builtin",
    "export",
    "declare",
    "typeset",
    "readonly",
    "local",
    "!",
    "if",
    "then",
    "else",
    "elif",
    "do",
    "while",
    "until",
}
# `declare -x` / `export -p` のような wrapper 直後の短フラグは透過にする。
# 汎用にトークン単体で判定すると `git push -o GIT_DIR=1` の `-o` まで拾って
# しまうため、直前が _ENV_WRAPPERS のときに限定する。
_WRAPPER_FLAG_RE = re.compile(r"^-[A-Za-z][A-Za-z0-9-]*$")
# wrapper option の値を 1 トークン取る形（`env -u NAME git ...` など）。値を
# wrapper 語と同じ扱いにすると、後続の git を引数位置と誤認して cwd へ戻してしまう。
_ENV_WRAPPER_VALUE_FLAGS = {"-u", "--unset"}

# git のうち値を取るオプション。`git commit -m "--work-tree"` のように値の中身が
# たまたまオプション名と同じ文字列でも、それは引数であってオプション指定では
# ないため option 検出から除外する。
_GIT_VALUE_TAKING_OPTIONS = ("-m", "--message", "-F", "--file")


def _has_git_option(tokens: list[str], names: tuple[str, ...]) -> bool:
    """`git` 呼び出し 1 個分（次の区切りまで）の範囲でだけオプションを検出する。

    範囲を絞らないと、後続コマンドの引数文字列（例: commit message）に同じ
    文字列が現れただけで誤検知する。
    """
    index = 0
    count = len(tokens)
    while index < count:
        if tokens[index] == "git" and _is_git_start(tokens, index):
            cursor = index + 1
            while cursor < count and tokens[cursor] not in _SEPARATORS:
                token = tokens[cursor]
                if token in _GIT_VALUE_TAKING_OPTIONS and cursor + 1 < count:
                    cursor += 2
                    continue
                if any(token == name or token.startswith(f"{name}=") for name in names):
                    return True
                cursor += 1
            index = cursor
            continue
        index += 1
    return False


def _is_env_prefix_position(tokens: list[str], index: int) -> bool:
    """tokens[index] がコマンドの env prefix 位置（実行時に環境へ効く位置）にあるか。

    コマンド起点、または起点から env 代入 / wrapper 語 / wrapper option（値を取る形も含む）
    だけを挟んだ位置を真とする。`echo "GIT_DIR=x"` のような引数位置の文字列は
    偽（誤検知を避ける）。
    """
    cursor = index - 1
    while cursor >= 0 and not _is_command_start(tokens, cursor + 1):
        previous = tokens[cursor]
        if previous in _ENV_WRAPPERS or _ENV_ASSIGNMENT_RE.match(previous):
            cursor -= 1
            continue
        if (
            cursor >= 2
            and tokens[cursor - 1] in _ENV_WRAPPER_VALUE_FLAGS
            and tokens[cursor - 2] in _ENV_WRAPPERS
        ):
            cursor -= 3
            continue
        if (
            (
                _WRAPPER_FLAG_RE.match(previous)
                or previous == "--"
            )
            and cursor > 0
            and tokens[cursor - 1] in _ENV_WRAPPERS
        ):
            cursor -= 2
            continue
        return False
    return True


def _env_prefix_names(tokens: list[str], names: tuple[str, ...]) -> bool:
    return any(
        token.startswith(f"{name}=") and _is_env_prefix_position(tokens, index)
        for index, token in enumerate(tokens)
        for name in names
    )


def unresolvable_reason(command: str) -> str | None:
    """対象 repo を一意に決められないグローバルオプション/env prefix を検出する。

    マッチしなければ None（このチェックだけでは解決不能と判定しない）。
    判定は正規表現ではなくトークン列で行う。`(^|\\s)` 境界の正規表現は
    `;GIT_DIR=/x git push` のように区切り文字直後へ空白なしで置いた代入を
    見落とし、承認対象と別の repo を操作できた（2026-08-29 Codex 監査で検出）。
    """
    tokens = _tokenize(command)
    if _has_git_option(tokens, _UNRESOLVABLE_GIT_OPTIONS):
        return "--git-dir / --work-tree を含むコマンドは work tree と git dir を分離できるため対象 repo を確定できません"
    if _env_prefix_names(tokens, _UNRESOLVABLE_GIT_ENV):
        return "GIT_DIR= / GIT_WORK_TREE= を含むコマンドは対象 repo を確定できません"
    return None


# シェルの制御演算子。トークン化後にコマンドの区切りとして扱う。
_SEPARATORS = {";", "&&", "||", "|", "&"}

# 値を取る git グローバルオプション（subcommand 開始検出のために値を読み飛ばす）。
# -C 自体は候補として収集するのでここには含めない。--git-dir=path / -c k=v の
# `=` 形式は 1 トークンなので値スキップ不要（non-option でもない）。
_GIT_GLOBAL_VALUE_OPTIONS = {
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--config-env",
}
# 抽出値にこれらが残っている場合は展開結果を推測できないため unresolvable にする。
_SHELL_EXPANSION_CHARS = ("$", "`")


def _is_command_start(tokens: list[str], index: int) -> bool:
    if index == 0:
        return True
    previous = tokens[index - 1]
    # "(" は subshell の開始。")" の直後に明示的な区切りが無く次のコマンドが続く形
    # （例: `(cd /x) cd /y`）は文法上は不正だが、推測せず fail-closed に倒すため
    # command start として扱う（見落とすと後続の cd/-C が抽出されず、複数 repo に
    # またがる形を単一 cd と誤認してしまう）。
    return previous in _SEPARATORS or previous in ("(", ")")


def _is_git_start(tokens: list[str], index: int) -> bool:
    """`git` トークンがコマンド起点にあるか（env/wrapper と `rtk git` を含む）。"""
    if _is_command_start(tokens, index):
        return True
    if index > 0 and tokens[index - 1] == "rtk":
        return _is_command_start(tokens, index - 1) or _is_env_prefix_position(tokens, index - 1)
    return _is_env_prefix_position(tokens, index)

def _tokenize(command: str) -> list[str]:
    """制御演算子（; & | && || ( )）を独立トークンとして保持しつつトークン化する。

    plain `shlex.split` は "(" / ")" を通常の word 文字として扱うため、subshell 形
    `(cd <repo-b> && git push)` では "(cd" が 1 トークンに融合し cd 抽出が効かない
    （push 本体は normalize の subshell 潰しでゲートには当たるが、対象 repo の解決
    だけが呼び出し元 base にフォールバックし、repo A の承認で repo B へ push できる
    穴になる。2026-07-26 に実測）。enforce-gwm-for-worktree.sh の python tokenizer
    と同じ流儀（punctuation_chars）でこれを防ぐ。
    """
    # 改行はコマンドの区切り。shlex は改行を空白としか見ないため、先に `;` へ
    # 寄せる（quote 内の改行も置換されるが、値の中身は判定に使わない）。
    try:
        lexer = shlex.shlex(
            command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()"
        )
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError as error:
        raise UnresolvableTarget(f"コマンドの引用符を解析できません: {error}") from error


def _extract_candidates(command: str) -> tuple[list[str], list[str], list[str]]:
    """CMD をトークン化し、(--cwd 値, git -C 値, cd 値) を出現順に抽出する。

    値の個数を返すのは呼び出し側で複数指定（repo をまたぐ形）を検出するため。
    """
    tokens = _tokenize(command)

    cwd_values: list[str] = []
    git_c_values: list[str] = []
    cd_values: list[str] = []

    index = 0
    count = len(tokens)
    while index < count:
        token = tokens[index]
        if token == "--cwd" and index + 1 < count:
            cwd_values.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith("--cwd="):
            cwd_values.append(token.split("=", 1)[1])
            index += 1
            continue
        if token == "cd" and _is_command_start(tokens, index) and index + 1 < count:
            cd_values.append(tokens[index + 1])
            index += 2
            continue
        if token == "git" and _is_git_start(tokens, index):
            # -C はグローバルオプション領域（git [options] <subcommand> の options
            # 部分）にあるときだけ repo 指定になる。subcommand 以降の `-C`
            # （例: `git commit -C HEAD` = --reuse-message）は対象 repo 指定では
            # ないため、最初の non-option トークン（= subcommand）で探索を打ち切る。
            # 値を取るグローバルオプション（-C/-c/--git-dir 等）は値を読み飛ばす。
            cursor = index + 1
            while cursor < count and tokens[cursor] not in _SEPARATORS:
                current = tokens[cursor]
                if not current.startswith("-"):
                    break
                if current == "-C" and cursor + 1 < count:
                    git_c_values.append(tokens[cursor + 1])
                    cursor += 2
                    continue
                if current in _GIT_GLOBAL_VALUE_OPTIONS and cursor + 1 < count:
                    cursor += 2
                    continue
                cursor += 1
            index = cursor
            continue
        index += 1

    return cwd_values, git_c_values, cd_values


def resolve_target(base: Path, command: str) -> Path:
    """CMD から対象 repo のディレクトリを解決する。

    優先順位（現状踏襲）: --cwd > git -C > cd。解決不能なら UnresolvableTarget。
    相対パスは base 基準で解決する（Path(token).resolve() はプロセス cwd 基準に
    なってしまうため使わない — P1-A の再発防止）。
    rev-parse toplevel 化はしない。返すのは解決したディレクトリそのもので、
    repo root への正規化は呼び出し元の責務。
    """
    reason = unresolvable_reason(command)
    if reason is not None:
        raise UnresolvableTarget(reason)

    cwd_values, git_c_values, cd_values = _extract_candidates(command)

    # 1 コマンドで複数 repo にまたがる形は、承認主体（どちらの repo か）を
    # 確定できないため推測しない。
    if len(cd_values) > 1:
        raise UnresolvableTarget("cd が複数回指定されているため対象 repo を一意に決定できません")
    if len(git_c_values) > 1:
        raise UnresolvableTarget("git -C が複数回指定されているため対象 repo を一意に決定できません")

    if cwd_values:
        candidate = cwd_values[0]
    elif git_c_values:
        candidate = git_c_values[0]
    elif cd_values:
        candidate = cd_values[0]
    else:
        # CMD に repo 切り替えの指定が無い。呼び出し元 cwd をそのまま維持する。
        return base

    if any(ch in candidate for ch in _SHELL_EXPANSION_CHARS):
        raise UnresolvableTarget(f"シェル展開を含む値は推測せず解決不能として扱います: {candidate}")

    target = Path(candidate).expanduser() if candidate.startswith("~") else Path(candidate)
    # target が絶対パスなら base は無視される（pathlib の仕様どおり）。相対パスは
    # base 基準で解決する。
    resolved = (base / target).resolve()

    if not resolved.is_dir():
        raise UnresolvableTarget(f"対象パスが存在しません: {resolved}")

    return resolved


# --- gh pr create の -R/--repo/GH_REPO=/--head 検査 ---
# 値の形（owner/repo か URL）を要求するのは、--body の Markdown 本文散文での
# 誤検知を避けるため（トークン化で quote 内の本文は 1 トークンに畳まれる）。
_GH_REPO_VALUE_RE = re.compile(r"^([\w.-]+/[\w.-]+|https?://\S+)$")
_GH_REPO_OPTIONS = ("--repo", "-R")

_GH_REPO_REASON = (
    "--repo/-R での別 repo への PR 作成はレビュー証跡と対応付けられません。"
    "対象 repo に cd してから実行してください"
)
_GH_HEAD_REASON = "--head で別ブランチの PR を作る形は、承認済み HEAD と対象が一致しません"


def _option_values(tokens: list[str], names: tuple[str, ...]) -> list[str]:
    """`--opt value` / `--opt=value` 両形の値を出現順に返す。"""
    values: list[str] = []
    for index, token in enumerate(tokens):
        for name in names:
            if token == name and index + 1 < len(tokens):
                values.append(tokens[index + 1])
            elif token.startswith(f"{name}="):
                values.append(token.split("=", 1)[1])
    return values


def gh_target_reason(command: str, current_branch: str) -> str | None:
    """gh pr create が cwd repo の current branch 以外を対象にしていないか判定する。

    解決不能（= 別 repo / 別ブランチを対象にしうる）なら理由文字列、
    cwd repo の current branch に確定できるなら None を返す。
    """
    try:
        tokens = _tokenize(command)
    except UnresolvableTarget as error:
        return error.reason

    if any(_GH_REPO_VALUE_RE.match(value) for value in _option_values(tokens, _GH_REPO_OPTIONS)):
        return _GH_REPO_REASON
    if _env_prefix_names(tokens, ("GH_REPO",)):
        return _GH_REPO_REASON

    for head_value in _option_values(tokens, ("--head",)):
        # owner:branch 形はフォークの branch を指すため、値が一致していても常に deny。
        if ":" in head_value or head_value != current_branch:
            return _GH_HEAD_REASON

    return None


# --- CLI（bash から呼ぶ。command は stdin 経由） ---


def _read_command_from_stdin() -> str:
    return sys.stdin.read()


def _cmd_resolve(args: argparse.Namespace) -> int:
    base = Path(args.base).expanduser().resolve()
    command = _read_command_from_stdin()
    try:
        target = resolve_target(base, command)
    except UnresolvableTarget as error:
        print(error.reason, file=sys.stderr)
        return 2
    print(str(target))
    return 0


def _cmd_gh_target(args: argparse.Namespace) -> int:
    command = _read_command_from_stdin()
    reason = gh_target_reason(command, args.current_branch)
    if reason is not None:
        print(reason, file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--base", required=True)

    gh_target_parser = commands.add_parser("gh-target")
    gh_target_parser.add_argument("--current-branch", required=True)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "resolve":
            return _cmd_resolve(args)
        return _cmd_gh_target(args)
    except UnresolvableTarget as error:
        print(error.reason, file=sys.stderr)
        return 2
    except (KeyError, TypeError, ValueError, OSError) as error:
        print(f"internal error: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
