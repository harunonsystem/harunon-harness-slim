#!/usr/bin/env python3
"""Assemble the Codex plugin marketplace from harunon-harness SSOT sources."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKELETON = REPO_ROOT / "packages/runtimes/codex/harunon-core"
POST_EDIT_ASSETS = ("post-edit-checks.sh", "fix_gfm_tables.py")

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from harness_lib.hook_pipeline import load as load_hook_pipeline  # noqa: E402
from harness_lib.hook_pipeline import pipeline as hook_pipeline  # noqa: E402


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)


def build(output: Path) -> Path:
    if output.exists():
        shutil.rmtree(output)
    plugin = output / "plugins/harunon-core"
    copy_tree(SKELETON, plugin)
    plugin_manifest = json.loads(
        (SKELETON / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    plugin_version = plugin_manifest["version"]
    copy_tree(REPO_ROOT / "packages/core/policy", plugin / "policy")
    copy_tree(REPO_ROOT / "packages/core/workflows", plugin / "workflows")
    # hook は plugin/hooks/ 直下に置く。hook 自身が $HOOK_DIR/../policy/ と
    # $HOOK_DIR/lib/ を参照するため、この配置でないと source / table 読み込みに失敗する
    # （hooks/libexec/ に置いていた間は enforce-gwm が lib を読めず、codex では全 Bash
    # コマンドが deny されていた）。同梱する hook は hook-pipeline.json が唯一の真実。
    hook_destination = plugin / "hooks"
    hook_destination.mkdir(parents=True, exist_ok=True)
    for name in hook_pipeline(load_hook_pipeline(REPO_ROOT), "codex"):
        shutil.copy2(REPO_ROOT / "packages/core/hooks" / name, hook_destination / name)
    copy_tree(REPO_ROOT / "packages/core/hooks/lib", hook_destination / "lib")
    # PostToolUse の post-edit チェックは hook-pipeline.json（PreToolUse guard/rewrite の
    # 共有表）の対象外なので hooks/ 直下ではなく hooks/post-edit/ に隔離して同梱する。
    # fix_gfm_tables.py は post-edit-checks.sh が $HOOK_DIR 隣接で参照する。
    post_edit = hook_destination / "post-edit"
    post_edit.mkdir(parents=True, exist_ok=True)
    for name in POST_EDIT_ASSETS:
        shutil.copy2(REPO_ROOT / "packages/core/hooks" / name, post_edit / name)
    output.mkdir(parents=True, exist_ok=True)
    codex_marketplace = {
        "name": "harunon-local",
        "interface": {"displayName": "Harunon Harness"},
        "plugins": [
            {
                "name": "harunon-core",
                "source": {"source": "local", "path": "./plugins/harunon-core"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }
    codex_manifest = output / ".agents/plugins/marketplace.json"
    codex_manifest.parent.mkdir(parents=True, exist_ok=True)
    codex_manifest.write_text(
        json.dumps(codex_marketplace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    discovery_marketplace = {
        "name": "harunon-local",
        "owner": {"name": "harunon-harness"},
        "metadata": {
            "description": "Cross-runtime workflow and policy adapter for Codex.",
            "version": plugin_version,
        },
        "plugins": [
            {
                "name": "harunon-core",
                "description": "Run the shared harunon workflow safely in Codex.",
                "version": plugin_version,
                "author": {"name": "harunon-harness"},
                "source": "./plugins/harunon-core",
            }
        ],
    }
    discovery_manifest = output / ".claude-plugin/marketplace.json"
    discovery_manifest.parent.mkdir(parents=True, exist_ok=True)
    discovery_manifest.write_text(
        json.dumps(discovery_marketplace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return plugin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "build/codex-marketplace",
    )
    args = parser.parse_args()
    plugin = build(args.output.resolve())
    print(plugin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
