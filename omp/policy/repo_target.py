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
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit


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


# --- gh PR repo/head selector inspection; option values remain data. ---
_GH_VALUE_OPTIONS = {
    '--repo', '-R', '--head', '-H', '--base', '-B', '--title', '-t', '--body', '-b',
    '--body-file', '-F', '--assignee', '-a', '--reviewer', '-r', '--label', '-l',
    '--milestone', '-m', '--project', '-p', '--template', '--recover', '--subject',
    '--author-email', '--match-head-commit',
}
_GH_REPO_OPTIONS = ("--repo", "-R")

_GH_REPO_REASON = (
    "--repo/-R の対象がローカル repo と一致しないか、一意に解決できません。"
    "対象 repo の checkout を作業ディレクトリにする subshell 形で同じ gh pr 操作を実行し、"
    "selector はその repo と一致させてください"
)
_GH_ENV_REASON = (
    "GH_REPO の対象がローカル repo と一致しないか、一意に解決できません。"
    "GH_REPO= の代入と --repo/-R をその repo と一致させるか、不一致の代入を除去し実行元で unset GH_REPO してください。"
    "対象 repo の checkout を作業ディレクトリにして同じ操作を実行してください"
)
_GH_HEAD_REASON = "--head で別ブランチの PR を作る形は、承認済み HEAD と対象が一致しません"


def _option_values(tokens: list[str], names: tuple[str, ...]) -> list[str]:
    """`--opt value` / `--opt=value` 両形の値を出現順に返す。"""
    values: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == '--':
            break
        name = token.split('=', 1)[0]
        if name in _GH_VALUE_OPTIONS:
            value = token.split('=', 1)[1] if '=' in token else tokens[index] if index < len(tokens) else ''
            if name in names:
                values.append(value)
            if '=' not in token:
                index += 1
            continue
        for short in _GH_VALUE_OPTIONS:
            if len(short) == 2 and token.startswith(short) and len(token) > 2:
                if short in names:
                    values.append(token[2:].removeprefix('='))
                break
    return values


def gh_target_reason(command: str, current_branch: str, repo: Path | None = None) -> str | None:
    """gh pr create が cwd repo の current branch 以外を対象にしていないか判定する。

    解決不能（= 別 repo / 別ブランチを対象にしうる）なら理由文字列、
    cwd repo の current branch に確定できるなら None を返す。
    """
    try:
        tokens = _tokenize(command)
    except UnresolvableTarget as error:
        return error.reason

    selectors = _option_values(tokens, _GH_REPO_OPTIONS)
    env_selectors = [token.split("=", 1)[1] for index, token in enumerate(tokens)
                     if token.startswith("GH_REPO=") and _is_env_prefix_position(tokens, index)]
    if os.environ.get("GH_REPO"):
        env_selectors.append(os.environ["GH_REPO"])
    hosts = [token.split("=", 1)[1] for index, token in enumerate(tokens)
             if token.startswith("GH_HOST=") and _is_env_prefix_position(tokens, index)]
    if os.environ.get("GH_HOST"):
        hosts.append(os.environ["GH_HOST"])
    try:
        expected = repository_identity(repo or Path.cwd())
        if hosts and any(host.lower() != expected.split("/", 1)[0] for host in hosts):
            return "GH_HOST の対象 host とローカル repo が一致しません"
        host = hosts[-1] if hosts else "github.com"
        values = [host + "/" + value if re.fullmatch(r"[\w.-]+/[\w.-]+", value) else value
                  for value in selectors + env_selectors]
        if any(canonical_repository(value, selector=True) != expected for value in values):
            return _GH_ENV_REASON if env_selectors else _GH_REPO_REASON
    except UnresolvableTarget as error:
        if selectors or env_selectors or hosts:
            return _GH_ENV_REASON if env_selectors else _GH_REPO_REASON
        return "gh の暗黙の対象 repo を確定できません: " + error.reason

    for head_value in _option_values(tokens, ("--head", "-H")):
        # owner:branch 形はフォークの branch を指すため、値が一致していても常に deny。
        if ":" in head_value or head_value != current_branch:
            return _GH_HEAD_REASON

    return None


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        raise UnresolvableTarget(f"git による対象解決に失敗しました: {' '.join(args)}")
    return result.stdout.strip()


def _config(repo: Path, key: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), "config", "--get-all", key], capture_output=True, text=True, timeout=10, check=False)
    if result.returncode not in (0, 1):
        raise UnresolvableTarget(f"git config を解決できません: {key}")
    return result.stdout.strip()


def canonical_repository(value: str, *, selector: bool = False) -> str:
    """Transport spellings share host/owner/repo; local paths stay filesystem identities."""
    if selector and re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        value = "https://github.com/" + value
    if "://" not in value and re.fullmatch(r"(?:[^@/:]+@)?[\w.-]+:.+", value):
        value = "ssh://" + value.replace(":", "/", 1)
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme not in ("https", "http", "ssh", "git") or not parsed.hostname or parsed.query or parsed.fragment:
            raise UnresolvableTarget("送信先 URL の形式を安全に解決できません")
        path = parsed.path.strip("/").removesuffix(".git")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", path):
            raise UnresolvableTarget("送信先の owner/repo を確定できません")
        host = parsed.hostname.lower()
        # GitHub repository names are case-insensitive; other hosts need exact paths.
        return host + (f":{parsed.port}" if parsed.port else "") + "/" + (path.lower() if host == "github.com" else path)
    if selector:
        if re.fullmatch(r"[\w.-]+/[\w.-]+/[\w.-]+", value):
            return canonical_repository("https://" + value)
        raise UnresolvableTarget("gh の対象 repo を確定できません")
    path = Path(value)
    if not path.is_absolute():
        raise UnresolvableTarget("相対 URL は送信先を確定できません")
    gitdir = Path(_git(path.resolve(strict=True), "rev-parse", "--absolute-git-dir")).stat()
    return f"local:{gitdir.st_dev}:{gitdir.st_ino}"


def repository_identity(repo: Path) -> str:
    remotes = _git(repo, "remote").splitlines()
    identities = {canonical_repository(url) for remote in remotes
                  for url in _git(repo, "remote", "get-url", "--all", remote).splitlines()}
    if len(identities) != 1:
        raise UnresolvableTarget("複数の repo 候補があるため gh 対象を確定できません")
    return identities.pop()


def checkout_identity(repo: Path) -> list[int]:
    # A rename/ghq move on the same filesystem preserves these identities. Copies,
    # independent clones and linked worktrees cannot inherit this approval.
    root = Path(_git(repo, "rev-parse", "--show-toplevel")).stat()
    gitdir = Path(_git(repo, "rev-parse", "--absolute-git-dir")).stat()
    return [root.st_dev, root.st_ino, gitdir.st_dev, gitdir.st_ino]


def approval_key(repo: Path) -> str:
    value = [checkout_identity(repo), _git(repo, "symbolic-ref", "--short", "HEAD")]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def push_target(repo: Path, command: str) -> dict:
    """Resolve one branch update or fully qualified branch deletion offline.

    Unsupported multi-ref/config override forms fail closed instead of simulating Git.
    """
    tokens = _tokenize(command)
    sensitive_env = ("GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_NAMESPACE", "GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE")
    if _env_prefix_names(tokens, sensitive_env) or any(os.environ.get(name) for name in sensitive_env):
        raise UnresolvableTarget("Git 環境の上書きは承認対象を確定できません")
    starts = [i for i, token in enumerate(tokens) if token == "git" and _is_git_start(tokens, i)]
    if len(starts) != 1:
        raise UnresolvableTarget("単独の push 対象を確定できません")
    i = starts[0] + 1
    while i < len(tokens) and tokens[i] != "push":
        if tokens[i] == "-C":
            i += 2
        else:
            raise UnresolvableTarget("git の設定上書きは承認対象を確定できません")
    if i == len(tokens):
        raise UnresolvableTarget("push を解析できません")
    args = tokens[i + 1:]
    positional = []
    delete = False
    update_options = False
    i = 0
    while i < len(args):
        token = args[i]
        i += 1
        if token in _SEPARATORS or token.startswith("2>"):
            break  # outer hook separately checks the read-only sink allowlist
        if token in ("--delete", "-d") or re.fullmatch(r"-[vqd]+", token):
            delete = delete or "d" in token
        elif token in ("-o", "--push-option"):
            update_options = True
            i += 1
        elif token.startswith(("--push-option=", "--force-with-lease=")) or (token.startswith("-o") and len(token) > 2) or token in ("-u", "--set-upstream", "--force-with-lease", "--dry-run", "-n", "--verbose", "-v", "--quiet", "-q", "--porcelain"):
            update_options = update_options or token not in ("--verbose", "-v", "--quiet", "-q", "--porcelain")
            continue
        elif token.startswith("-"):
            raise UnresolvableTarget("push の repo 指定・複数 ref・未知の option は承認では通せません")
        else:
            if any(char in token for char in _SHELL_EXPANSION_CHARS):
                raise UnresolvableTarget("展開を含む push 対象は確定できません")
            positional.append(token)
    if len(positional) > 2:
        raise UnresolvableTarget("複数 ref の push は承認では通せません")
    branch = _git(repo, "symbolic-ref", "--short", "HEAD")
    if _config(repo, "push.followTags") not in ("", "false", "no", "0") or _config(repo, "push.recurseSubmodules") not in ("", "no", "false", "0"):
        raise UnresolvableTarget("追加 tag / submodule の push は承認では通せません")
    remotes = _git(repo, "remote").splitlines()
    remote = positional[0] if positional else (_config(repo, f"branch.{branch}.pushRemote") or _config(repo, "remote.pushDefault") or _config(repo, f"branch.{branch}.remote"))
    if not remote:
        remote = "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else ""
    if not remote:
        raise UnresolvableTarget("push remote を一意に確定できません")
    if remote in remotes:
        urls = _git(repo, "remote", "get-url", "--push", "--all", remote).splitlines()
        if len(urls) != 1 or _config(repo, f"remote.{remote}.mirror") not in ("", "false", "no", "0"):
            raise UnresolvableTarget("複数 pushurl / mirror は承認では通せません")
    else:
        # get-url applies insteadOf/pushInsteadOf only to configured remotes.
        rewrites = subprocess.run(["git", "-C", str(repo), "config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$"], capture_output=True, text=True, timeout=10, check=False)
        if rewrites.returncode != 1:
            raise UnresolvableTarget("直接 URL と URL rewrite の併用は対象を確定できません")
        urls = [remote]
    if len(positional) == 2:
        refspec = positional[1]
        source, separator, destination = refspec.partition(":")
        delete = delete or (bool(separator) and not source)
        if delete:
            if update_options or (separator and source) or not (destination or source):
                raise UnresolvableTarget("削除は単独の branch ref だけを明示してください")
            destination = destination if separator else source
            if not destination.startswith("refs/heads/"):
                raise UnresolvableTarget("削除 ref は refs/heads/... の完全修飾名で明示してください（短い名・tag・任意 namespace は承認できません）")
        elif separator and not destination.startswith("refs/heads/"):
            raise UnresolvableTarget("明示 refspec の送信先は refs/heads/... で指定してください")
        else:
            destination = destination or source
        if not delete:
            if source not in ("HEAD", branch, "refs/heads/" + branch):
                raise UnresolvableTarget("承認は現在の HEAD の push だけに適用されます")
            if destination == "HEAD":
                destination = branch
    else:
        if delete:
            raise UnresolvableTarget("削除する remote と branch ref を明示してください")
        if remote in remotes and _config(repo, f"remote.{remote}.push"):
            raise UnresolvableTarget("remote.push refspec は明示してください")
        mode = _config(repo, "push.default") or "simple"
        upstream_remote = _config(repo, f"branch.{branch}.remote")
        merge = _config(repo, f"branch.{branch}.merge")
        if mode == "current" or (mode == "simple" and remote != upstream_remote):
            destination = branch
        elif mode in ("upstream", "simple") and remote == upstream_remote and merge:
            destination = merge
            if mode == "simple" and merge != "refs/heads/" + branch:
                raise UnresolvableTarget("simple push の upstream branch が一致しません")
        else:
            raise UnresolvableTarget("push.default の対象を一意に確定できません。refspec を明示してください")
    if not destination.startswith("refs/"):
        destination = "refs/heads/" + destination
    if not destination.startswith("refs/heads/") or destination in ("refs/heads/main", "refs/heads/master"):
        raise UnresolvableTarget("保護 ref / branch 以外への push は承認では通せません")
    _git(repo, "check-ref-format", destination)
    return {"operation": "git.push.delete" if delete else "git.push", "checkout": checkout_identity(repo), "branch": branch,
            "head": _git(repo, "rev-parse", "HEAD"), "repository": canonical_repository(urls[0]),
            "ref": destination}


def pr_target(repo: Path, command: str) -> dict:
    tokens = _tokenize(command)
    starts = [i for i in range(len(tokens) - 2) if tokens[i:i + 2] == ["gh", "pr"] and _is_env_prefix_position(tokens, i)]
    if len(starts) != 1:
        raise UnresolvableTarget("単独の PR 操作を確定できません")
    args = tokens[starts[0] + 2:]
    if len(args) < 2 or args[0] not in ("merge", "close") or not re.fullmatch(r"[1-9][0-9]*", args[1]):
        raise UnresolvableTarget("PR 操作と番号を明示してください")
    cursor = 2
    while cursor < len(args):
        token = args[cursor]
        cursor += 1
        if token in ("--merge", "--squash", "--rebase") and args[0] == "merge":
            continue
        if token in _GH_REPO_OPTIONS:
            cursor += 1
        elif token.startswith(("--repo=", "-R")):
            continue
        else:
            raise UnresolvableTarget("追加副作用 / 未知の PR option は承認では通せません")
    branch = _git(repo, "symbolic-ref", "--short", "HEAD")
    reason = gh_target_reason(command, branch, repo)
    if reason:
        raise UnresolvableTarget(reason)
    return {"operation": "pr." + args[0], "checkout": checkout_identity(repo), "branch": branch,
            "head": _git(repo, "rev-parse", "HEAD"), "repository": repository_identity(repo), "number": args[1]}


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
    reason = gh_target_reason(command, args.current_branch, Path.cwd())
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

    commands.add_parser("approval-key")
    commands.add_parser("push-target")
    check_parser = commands.add_parser("push-check")
    check_parser.add_argument("--flag", type=Path, required=True)
    commands.add_parser("pr-target")
    pr_check_parser = commands.add_parser("pr-check")
    pr_check_parser.add_argument("--flag", type=Path, required=True)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "resolve":
            return _cmd_resolve(args)
        if args.command == "gh-target":
            return _cmd_gh_target(args)
        if args.command == "approval-key":
            print(approval_key(Path.cwd()))
            return 0
        is_pr = args.command.startswith("pr-")
        target = (pr_target if is_pr else push_target)(Path.cwd(), _read_command_from_stdin())
        if args.command in ("push-target", "pr-target"):
            print(json.dumps(target, ensure_ascii=False, sort_keys=True))
            return 0
        try:
            approved = json.loads(args.flag.read_text())
        except (OSError, ValueError) as error:
            raise UnresolvableTarget("有効な送信先付き承認がありません。承認スクリプトで再承認してください") from error
        if not isinstance(approved, dict) or approved.get("head") != target["head"]:
            raise UnresolvableTarget("承認後に HEAD が変わったため再承認が必要です")
        if approved != target:
            raise UnresolvableTarget("承認済みの操作・checkout・branch・送信先・ref/PR 番号と一致しません" + (f"（対象 PR #{target['number']}）" if is_pr else ""))
        ttl = int(os.environ.get("PR_APPROVAL_TTL_SECONDS" if is_pr else "PUSH_APPROVAL_TTL_SECONDS", "1800"))
        age = time.time() - args.flag.stat().st_mtime
        if ttl < 0 or age < 0 or age > ttl:
            args.flag.unlink()
            raise UnresolvableTarget("承認は TTL により失効しました")
        if is_pr:
            return 0
        if target["operation"] == "git.push.delete":
            args.flag.unlink()
            return 0
        for remote in _git(Path.cwd(), "remote").splitlines():
            urls = _git(Path.cwd(), "remote", "get-url", "--push", "--all", remote).splitlines()
            if len(urls) != 1 or canonical_repository(urls[0]) != target["repository"]:
                continue
            fetch_urls = _git(Path.cwd(), "remote", "get-url", "--all", remote).splitlines()
            if len(fetch_urls) != 1 or canonical_repository(fetch_urls[0]) != target["repository"]:
                continue
            tracking = "refs/remotes/" + remote + "/" + target["ref"].removeprefix("refs/heads/")
            result = subprocess.run(["git", "rev-parse", "--verify", tracking], capture_output=True, text=True, timeout=10, check=False)
            if result.returncode == 0 and result.stdout.strip() == target["head"]:
                args.flag.unlink()
                raise UnresolvableTarget("この HEAD は対象 remote に到達済みで承認は失効しました")
        return 0
    except UnresolvableTarget as error:
        print(error.reason, file=sys.stderr)
        return 2
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"internal error: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
