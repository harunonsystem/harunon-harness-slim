"""global mise（`~/.config/mise/config.toml`）の宣言 vs 実機ドリフト検出。

SSOT は repo ルートの `mise.global.example.toml`（`[env]` と `[tools]` のキー集合）。
実機の global mise config と突き合わせ、env の欠落・値の不一致・tool の未インストールを
検出する。tool は名前の有無だけを見て、バージョン差分は対象外とする（
`packages/targets/pi/config.json` の notes にある通り、live バージョンは意図的に pin
されるため drift 扱いしない）。

CLI:
    python3 scripts/mise-global-check.py [--example PATH] [--config PATH]
        [--apply-env] [--yes]

exit 0: drift なし（またはツール未インストールのみで env は宣言どおり、--apply-env 適用後に
    env drift が解消した場合）
exit 1: env drift あり（未適用、またはユーザーがスキップして残った場合）
exit 2: 実行時エラー（不正な TOML 等）
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Expected:
    env: dict[str, str]
    tools: frozenset[str]


@dataclass(frozen=True)
class Finding:
    kind: str  # "env-missing" | "env-differs" | "tool-missing"
    key: str
    expected: str | None = None
    actual: str | None = None


def _load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML: {path}") from exc


def _to_expected(data: dict) -> Expected:
    env_raw = data.get("env", {})
    env = {k: str(v) for k, v in env_raw.items()}
    tools = frozenset(data.get("tools", {}).keys())
    return Expected(env=env, tools=tools)


def load_expected(example_path: Path) -> Expected:
    return _to_expected(_load_toml(example_path))


def load_live(config_path: Path) -> Expected:
    if not config_path.is_file():
        return Expected(env={}, tools=frozenset())
    return _to_expected(_load_toml(config_path))


def compare(expected: Expected, live: Expected) -> list[Finding]:
    findings: list[Finding] = []
    for key, value in expected.env.items():
        if key not in live.env:
            findings.append(Finding("env-missing", key, expected=value))
        elif live.env[key] != value:
            findings.append(Finding("env-differs", key, expected=value, actual=live.env[key]))
    for tool in sorted(expected.tools):
        if tool not in live.tools:
            findings.append(Finding("tool-missing", tool))
    return findings


def render(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        if f.kind == "env-missing":
            lines.append(f"env 未設定: {f.key} (期待値: {f.expected})")
        elif f.kind == "env-differs":
            lines.append(f"env 不一致: {f.key} (期待値: {f.expected} / 実際: {f.actual})")
        elif f.kind == "tool-missing":
            lines.append(f"tool 未インストール: {f.key}")
    return "\n".join(lines)


_ENV_HEADER_RE = re.compile(r"^\[env\]\s*$")
_SECTION_HEADER_RE = re.compile(r"^\[.+\]\s*$")


def apply_env_key(config_path: Path, key: str, value: str) -> None:
    """`[env]` テーブルの1キーだけをテキスト編集で更新/追記する。

    tomllib/tomli-w で往復させるとコメント・順序が失われるため、対象行だけを
    最小差分で書き換える。`[env]` セクションが無ければファイル末尾に新設する。
    """
    original = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    had_trailing_newline = original.endswith("\n") or original == ""
    lines = original.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    key_line_re = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    new_line = f'{key} = "{value}"'

    env_start = None
    for i, line in enumerate(lines):
        if _ENV_HEADER_RE.match(line):
            env_start = i
            break

    if env_start is None:
        # [env] セクションが存在しない: 末尾に新設する
        new_lines = lines + (["", "[env]", new_line] if lines else ["[env]", new_line])
        config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return

    env_end = len(lines)
    for i in range(env_start + 1, len(lines)):
        if _SECTION_HEADER_RE.match(lines[i]):
            env_end = i
            break

    for i in range(env_start + 1, env_end):
        if key_line_re.match(lines[i]):
            lines[i] = new_line
            text = "\n".join(lines) + ("\n" if had_trailing_newline else "")
            config_path.write_text(text, encoding="utf-8")
            return

    # セクションはあるがキーが無い: セクション末尾に追記
    lines.insert(env_end, new_line)
    text = "\n".join(lines) + ("\n" if had_trailing_newline else "")
    config_path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--example", type=Path, default=repo_root / "mise.global.example.toml")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="既定は $MISE_GLOBAL_CONFIG、無ければ ~/.config/mise/config.toml",
    )
    p.add_argument("--apply-env", action="store_true")
    p.add_argument("--yes", action="store_true")
    ns = p.parse_args(argv)

    import os

    example_path = Path(str(ns.example)).expanduser()
    if ns.config is not None:
        config_path = Path(str(ns.config)).expanduser()
    else:
        config_path = Path(
            os.environ.get("MISE_GLOBAL_CONFIG", "~/.config/mise/config.toml")
        ).expanduser()

    try:
        expected = load_expected(example_path)
        live = load_live(config_path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    findings = compare(expected, live)

    if not ns.apply_env:
        if not findings:
            print("global mise: 宣言どおり")
            return 0
        print(render(findings))
        return 1

    if not findings:
        print("global mise: 宣言どおり")
        return 0

    for f in list(findings):
        if f.kind not in ("env-missing", "env-differs"):
            continue
        if ns.yes:
            do_apply = True
        else:
            answer = input(f"{f.key} を {f.expected} に設定しますか？ [y/N] ")
            do_apply = answer.strip().lower() in ("y", "yes")
        if do_apply:
            apply_env_key(config_path, f.key, f.expected or "")
        else:
            print(f"⊘ {f.key} はスキップしました")

    live_after = load_live(config_path)
    remaining = [
        f for f in compare(expected, live_after) if f.kind in ("env-missing", "env-differs")
    ]
    if remaining:
        print(render(remaining))
        return 1
    print("global mise env: 反映済み")
    return 0


if __name__ == "__main__":
    sys.exit(main())
