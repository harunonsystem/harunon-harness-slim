#!/usr/bin/env python3
"""Search a source tree with a dependency-free BM25 index."""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_CHUNK_LINES = 40
DEFAULT_TOP_K = 8
DEFAULT_SNIPPET_LINES = 8
DEFAULT_MAX_OUTPUT_CHARS = 12_000
DEFAULT_MAX_FILE_BYTES = 512_000
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "__pycache__",
        ".cache",
        ".next",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)
SECRET_NAMES = frozenset({"id_rsa", "id_ed25519", "id_ecdsa"})
SECRET_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx"})
_CAMEL_ACRONYM_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Chunk:
    """A fixed-size source fragment and its pre-tokenized search document."""

    path: Path
    start_line: int
    end_line: int
    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


def tokenize(text: str) -> list[str]:
    """Split prose and common code identifiers into lowercase search terms."""
    expanded = _CAMEL_ACRONYM_RE.sub(r"\1 \2", text)
    expanded = _CAMEL_BOUNDARY_RE.sub(" ", expanded)
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(expanded)]


def _is_secret_path(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in SECRET_NAMES
        or name == ".env"
        or name.startswith(".env.")
        or path.suffix.lower() in SECRET_SUFFIXES
    )


def iter_source_files(root: Path, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> Iterable[Path]:
    """Yield readable-looking source files while avoiding generated and secret data."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"search root is not a directory: {root}")

    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in IGNORED_DIRS and not (Path(current) / name).is_symlink()
        )
        for name in sorted(filenames):
            path = Path(current) / name
            if path.is_symlink() or _is_secret_path(path):
                continue
            try:
                if not path.is_file() or path.stat().st_size > max_file_bytes:
                    continue
            except OSError:
                continue
            yield path


def _read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def build_chunks(
    root: Path,
    chunk_lines: int = DEFAULT_CHUNK_LINES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[Chunk]:
    """Build deterministic fixed-line chunks from a source tree."""
    if chunk_lines < 1:
        raise ValueError("chunk_lines must be positive")

    root = root.resolve()
    chunks: list[Chunk] = []
    for path in iter_source_files(root, max_file_bytes=max_file_bytes):
        text = _read_text(path)
        if text is None:
            continue
        lines = text.splitlines()
        if not lines:
            continue
        relative_path = path.relative_to(root)
        path_tokens = tokenize(relative_path.as_posix())
        for start in range(0, len(lines), chunk_lines):
            end = min(start + chunk_lines, len(lines))
            block = "\n".join(lines[start:end])
            tokens = tuple(path_tokens + tokenize(block))
            chunks.append(
                Chunk(
                    path=relative_path,
                    start_line=start + 1,
                    end_line=end,
                    text=block,
                    tokens=tokens,
                )
            )
    return chunks


def rank_chunks(
    query: str,
    chunks: Sequence[Chunk],
    limit: int = DEFAULT_TOP_K,
    k1: float = 1.2,
    b: float = 0.75,
) -> list[ScoredChunk]:
    """Rank chunks with Okapi BM25 and deterministic tie-breaking."""
    if limit < 1:
        raise ValueError("limit must be positive")
    query_terms = tuple(dict.fromkeys(tokenize(query)))
    if not query_terms or not chunks:
        return []

    document_frequency: Counter[str] = Counter()
    lengths: list[int] = []
    term_counts: list[Counter[str]] = []
    for chunk in chunks:
        counts = Counter(chunk.tokens)
        term_counts.append(counts)
        lengths.append(len(chunk.tokens))
        document_frequency.update(counts.keys())

    average_length = sum(lengths) / len(lengths)
    scored: list[ScoredChunk] = []
    for chunk, counts, length in zip(chunks, term_counts, lengths):
        score = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if frequency == 0:
                continue
            document_count = document_frequency[term]
            inverse_document_frequency = math.log(
                1.0 + (len(chunks) - document_count + 0.5) / (document_count + 0.5)
            )
            denominator = frequency + k1 * (
                1.0 - b + b * length / average_length
            )
            score += inverse_document_frequency * (frequency * (k1 + 1.0)) / denominator
        if score > 0.0:
            scored.append(ScoredChunk(chunk=chunk, score=score))

    scored.sort(
        key=lambda item: (
            -item.score,
            item.chunk.path.as_posix(),
            item.chunk.start_line,
        )
    )
    return scored[:limit]


def _snippet_window(chunk: Chunk, query_terms: Sequence[str], max_lines: int) -> tuple[int, int]:
    lines = chunk.text.splitlines()
    if len(lines) <= max_lines:
        return 0, len(lines)
    line_scores = [sum(token in tokenize(line) for token in query_terms) for line in lines]
    best_start = max(
        range(len(lines) - max_lines + 1),
        key=lambda start: (sum(line_scores[start : start + max_lines]), -start),
    )
    return best_start, best_start + max_lines


def render_results(
    query: str,
    results: Sequence[ScoredChunk],
    chunk_count: int,
    snippet_lines: int = DEFAULT_SNIPPET_LINES,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> str:
    """Render concise, line-addressable results for an agent context."""
    query_terms = tuple(dict.fromkeys(tokenize(query)))
    lines = [
        f"BM25 code search: chunks={chunk_count}, results={len(results)}, query={query!r}"
    ]
    if not results:
        lines.append("No matching code chunks.")
        return "\n".join(lines) + "\n"

    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        lines.append(
            f"{index}. {chunk.path.as_posix()}:{chunk.start_line}-{chunk.end_line} "
            f"score={result.score:.3f}"
        )
        start, end = _snippet_window(chunk, query_terms, snippet_lines)
        for offset in range(start, end):
            source_line = chunk.text.splitlines()[offset]
            if len(source_line) > 240:
                source_line = source_line[:237] + "..."
            lines.append(f"   {chunk.start_line + offset:>5} | {source_line}")

        rendered = "\n".join(lines) + "\n"
        if len(rendered) > max_output_chars:
            lines.pop()
            lines.append("... output truncated; reduce --top-k or --snippet-lines")
            break
    return "\n".join(lines) + "\n"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="terms to search for")
    parser.add_argument("root", nargs="?", default=".", help="source tree (default: .)")
    parser.add_argument("--top-k", type=_positive_int, default=DEFAULT_TOP_K)
    parser.add_argument("--chunk-lines", type=_positive_int, default=DEFAULT_CHUNK_LINES)
    parser.add_argument("--snippet-lines", type=_positive_int, default=DEFAULT_SNIPPET_LINES)
    parser.add_argument(
        "--max-output-chars",
        type=_positive_int,
        default=DEFAULT_MAX_OUTPUT_CHARS,
    )
    parser.add_argument(
        "--max-file-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_FILE_BYTES,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).expanduser()
    try:
        chunks = build_chunks(
            root,
            chunk_lines=args.chunk_lines,
            max_file_bytes=args.max_file_bytes,
        )
        results = rank_chunks(args.query, chunks, limit=args.top_k)
    except ValueError as error:
        print(f"bm25-search: {error}", file=sys.stderr)
        return 2

    sys.stdout.write(
        render_results(
            args.query,
            results,
            chunk_count=len(chunks),
            snippet_lines=args.snippet_lines,
            max_output_chars=args.max_output_chars,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
