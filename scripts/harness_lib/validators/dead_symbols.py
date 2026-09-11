"""scripts/ 配下で、どこからも参照されていない def / class を warn として報告する。

呼び出しグラフではなく**名前の出現回数**で判定する。このリポジトリは validator
registry（`CHECKS` の名前引き）や settings.json / hook-pipeline.json の文字列参照で
関数・ファイルを間接的に指すため、import と呼び出しだけを辿る方式（vulture 等）では
生きているコードを dead と誤判定する。

判定は 2 段構え:
  1. scripts/**/*.py を走査し、定義行以外に名前が出てこない候補を集める
  2. 候補だけをリポジトリ全文（JSON・shell・JS・Markdown 含む）で再検索し、
     文字列参照が 1 件でもあれば生存とみなす

再帰関数は自分自身の呼び出しで出現回数が増えるため検出できない。取りこぼす側に
倒しているので warn 止まりとし、error にはしない。
"""
from __future__ import annotations

import ast
from pathlib import Path

from ..validator_registry import Finding

_CHECK = "dead-symbols"

# 定義を集める対象。tests は「テストからしか呼ばれない本番コード」も検出したいので
# 走査対象から外す（テスト自身の fixture が dead 判定されるのも防ぐ）。
_SCAN_ROOT = "scripts"
_EXCLUDED_PARTS = frozenset({"tests"})

# 候補の生存確認で読むファイル。文字列参照を拾うため .py 以外も含める。
_REFERENCE_ROOTS = ("scripts", "packages", "schemas", ".githooks")
_REFERENCE_SUFFIXES = frozenset(
    {".py", ".json", ".jsonc", ".sh", ".js", ".ts", ".mjs", ".md", ".toml", ".yml"}
)


def _python_sources(repo_root: Path) -> list[Path]:
    scan_root = repo_root / _SCAN_ROOT
    if not scan_root.is_dir():
        return []
    return sorted(
        path
        for path in scan_root.rglob("*.py")
        if not _EXCLUDED_PARTS & set(path.relative_to(repo_root).parts)
    )


def _definitions(sources: list[Path], repo_root: Path) -> dict[str, str]:
    """定義名 -> "<相対パス>:<行番号>" を返す（同名は最初の定義を採用）。"""
    found: dict[str, str] = {}
    for path in sources:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # 構文エラーはテスト実行が拾う。ここでは判定材料にしない。
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            # dunder は Python 側が呼ぶ。test_ は unittest が名前規約で拾う。
            if node.name.startswith("__") or node.name.startswith("test_"):
                continue
            found.setdefault(node.name, f"{path.relative_to(repo_root)}:{node.lineno}")
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _reference_corpus(repo_root: Path) -> str:
    """候補の生存確認に使う全文。宣言済みルート配下のテキストファイルを連結する。"""
    chunks: list[str] = []
    for root_name in _REFERENCE_ROOTS:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        chunks.extend(
            _read(path)
            for path in root.rglob("*")
            if path.is_file() and path.suffix in _REFERENCE_SUFFIXES
        )
    return "\n".join(chunks)


def check_dead_symbols(repo_root: Path) -> list[Finding]:
    sources = _python_sources(repo_root)
    definitions = _definitions(sources, repo_root)
    if not definitions:
        return []

    # 1 段目: scripts/ の Python 本文だけで出現回数を数える（定義行の 1 回のみ = 候補）。
    python_corpus = "\n".join(_read(path) for path in sources)
    candidates = {
        name: location
        for name, location in definitions.items()
        if python_corpus.count(name) <= 1
    }
    if not candidates:
        return []

    # 2 段目: 候補だけをリポジトリ全文で再検索し、文字列参照があれば生存扱い。
    corpus = _reference_corpus(repo_root)
    return [
        Finding(
            check=_CHECK,
            level="warn",
            message=f"{location}: {name} はどこからも参照されていません（削除するか、参照元を確認する）",
        )
        for name, location in sorted(candidates.items())
        if corpus.count(name) <= 1
    ]
