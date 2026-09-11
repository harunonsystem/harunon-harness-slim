#!/usr/bin/env python3
"""公開 slim 配布物（harunon-harness-slim / harunon-pi-agent-slim）を SSOT から生成する。

Usage:
    build-public-slim.py [--output DIR] [--only harness|pi-agent] [--env-file PATH]
    build-public-slim.py --check [--env-file PATH]

宣言は packages/public-slim/manifest.json（allowlist / exclude / 加工 / gate）。ロジックは
scripts/harness_lib/public_slim.py。生成物は public 側の SSOT ではない: public を直接編集
しても次の生成で巻き戻る。

--output:   出力先（省略時 build/public-slim/）。既存なら消してから書く
--only:     片方だけ生成する。pi-agent は harness-slim から導くため、単独指定でも harness-slim
            を一時的に組む
--check:    一時ディレクトリに生成してゲートだけ回す（CI 用）。exit 0 = 通過
--env-file: ゲートの BLOCKED_TERMS を読む .env（省略時 repo ルートの .env）。テストが実 .env を
            触らず fail-close を再現するための seam
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib.runtime import require_supported_python  # noqa: E402

require_supported_python()

from harness_lib import public_slim  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "build/public-slim"


def build(output: Path, only: str | None, env_file: Path | None) -> int:
    manifest = public_slim.load_manifest(REPO_ROOT)
    harness_out = output / public_slim.HARNESS_SLIM_DIR
    pi_out = output / public_slim.PI_AGENT_SLIM_DIR
    output.mkdir(parents=True, exist_ok=True)

    report = public_slim.build_harness_slim(REPO_ROOT, manifest, harness_out)
    print(f"{public_slim.HARNESS_SLIM_DIR}: {len(report.included)} files")
    for line in report.dropped_includes:
        print(f"  dropped include line: {line}")
    for line in report.dropped_sources:
        print(f"  dropped distribute source: {line}")
    for line in report.dropped_commands:
        print(f"  dropped commands.md row: /{line}")
    for line in report.scale_rewrites:
        print(f"  rewrote CONTEXT.md scale count: {line}")

    roots = {public_slim.HARNESS_SLIM_DIR: harness_out}
    if only != "harness":
        install_manifest = public_slim.build_pi_agent_slim(REPO_ROOT, harness_out, pi_out)
        print(
            f"{public_slim.PI_AGENT_SLIM_DIR}: {len(install_manifest['managedPaths'])} managed paths, "
            f"{len(install_manifest['settingsKeys'])} settings keys"
        )
        roots[public_slim.PI_AGENT_SLIM_DIR] = pi_out

    result = public_slim.run_gate(REPO_ROOT, manifest, roots, env_file)
    print(public_slim.render_gate(result))
    if only == "pi-agent":
        # pi payload は harness-slim から導いた後なので、中間物は残さない
        import shutil

        shutil.rmtree(harness_out)
    return 0 if result.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="公開 slim 配布物の生成とゲート")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", choices=("harness", "pi-agent"), default=None)
    parser.add_argument("--check", action="store_true", help="一時ディレクトリに生成してゲートだけ回す")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()
    try:
        if args.check:
            with tempfile.TemporaryDirectory(prefix="public-slim-check.") as tmp:
                return build(Path(tmp), None, args.env_file)
        return build(args.output, args.only, args.env_file)
    except public_slim.SlimBuildError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
