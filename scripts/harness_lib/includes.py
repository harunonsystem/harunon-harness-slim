"""harness_lib.includes — テンプレートへの fragment 取り込み（transclusion）。

`<!-- include: <repo相対パス> -->` 行を、そのファイルの内容で置換する。
配布時に各ターゲットの薄型 AGENTS.md テンプレートが共有 fragment
（packages/core/fragments/ 配下）を取り込むために使う。

subtractive な patches（Claude 用 1 枚から剥がす）と対になる additive 方式:
各ターゲットは「何を含めるか」を include で宣言的に組み立てる。
"""
from __future__ import annotations

import re
from pathlib import Path

from .paths import safe_relative

# 行全体が include ディレクティブのときのみマッチ（行頭・行末の空白は許容）
# public_slim が「出力 tree に無い fragment を指す include 行」を落とす判定にも使う
INCLUDE_RE = re.compile(
    r"^[ \t]*<!--\s*include:\s*(?P<path>\S+)\s*-->[ \t]*$", re.MULTILINE
)


def _validate_include_path(path_str: str, repo: Path) -> None:
    """include パスが repo 内に閉じていることを検証する。

    symlink の実体まで確認する。文字列検査だけだと repo 内の symlink 経由で repo 外を
    読めてしまい、その内容が配布物へ埋め込まれる（2026-07-26 に実測。~/.ssh や
    API key の流出経路になる）。resolver._collect_dir が symlink を辿らない方針と揃える。
    """
    safe_relative(path_str, "include", base=repo)


def expand_includes(text: str, repo: Path) -> str:
    """text 内の include ディレクティブを fragment の内容で置換して返す。

    - 置換は 1 パス（fragment 内の include はサポートしない = fail fast）
    - fragment の末尾改行は正規化し、テンプレート側の前後空行で節を区切る
    - fragment が存在しなければ FileNotFoundError（dangling 防止）
    - 字面の検証（絶対パス・'..'）に加え、resolve() 後の実パスが repo 配下に
      収まっているかも検証する。repo 内 symlink が repo 外を指す場合、字面上は
      repo 内パスに見えても展開先が任意ファイルになり得るため（symlink 経由の
      パストラバーサル防止）。
    """
    repo_real = repo.resolve()

    def _repl(m: re.Match) -> str:
        rel = m.group("path")
        _validate_include_path(rel, repo)
        frag_path = repo / rel
        if not frag_path.is_file():
            raise FileNotFoundError(f"include 先が存在しません: {rel}")
        real_path = frag_path.resolve()
        try:
            real_path.relative_to(repo_real)
        except ValueError:
            raise ValueError(f"include 先が repo の外を指しています（symlink 経由か確認）: {rel}")
        fragment = real_path.read_text(encoding="utf-8").rstrip("\n")
        if INCLUDE_RE.search(fragment):
            raise ValueError(f"fragment 内の入れ子 include は未対応: {rel}")
        return fragment

    return INCLUDE_RE.sub(_repl, text)
