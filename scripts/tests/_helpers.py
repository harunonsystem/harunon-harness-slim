"""テスト用フィクスチャビルダー。

make_repo(tmp_path) で packages/targets/config.json + packages/core/... を
最小限のファイル構成で組み立てる。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# このファイルは scripts/tests/_helpers.py にある（1段上がると scripts/）
_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent


def run_distribute_cli(args: list) -> tuple:
    """distribute.py を subprocess で実行し (exit_code, stdout+stderr) を返す。"""
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "distribute.py")] + list(args),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def make_repo(tmp: Path) -> Path:
    """最小構成のテスト用リポジトリを tmp に作成し、repo_root を返す。

    作成するファイル:
      - packages/targets/claude/config.json
      - packages/targets/codex/config.json
      - packages/targets/opencode/config.json
      - packages/core/CLAUDE.md（テスト用コンテンツ）
      - packages/core/RTK.md
      - packages/core/commands.md
      - packages/core/rules/core-standards.md
      - packages/core/skills/demo-skill/SKILL.md
      - packages/core/skills/demo-skill/icon.png（ダミーバイナリ）
    """
    root = tmp

    # --- schemas: 本物の schemas/ を丸ごとコピー（target_config_errors 等が
    # schema ファイルを必須の契約として要求するため）---
    shutil.copytree(str(_SCRIPTS_DIR.parent / "schemas"), str(root / "schemas"))

    # --- extras: 空のサブモジュールパスとして作成（未取得相当） ---
    # resolver が "gitmodules 宣言済み＋空" を skip するための .gitmodules を用意
    (root / "packages" / "extras" / "_active" / "skills").mkdir(parents=True)
    (root / "packages" / "extras" / "_active" / "rules").mkdir(parents=True)
    (root / ".gitmodules").write_text(
        "[submodule \"packages/extras/_active\"]\n"
        "\tpath = packages/extras/_active\n"
        "\turl = git@github.com:example/extras.git\n",
        encoding="utf-8",
    )

    # --- core ファイル ---
    core = root / "packages" / "core"
    (core / "rules").mkdir(parents=True)
    (core / "skills" / "demo-skill").mkdir(parents=True)
    (core / "agents").mkdir(parents=True)
    (core / "commands").mkdir(parents=True)
    (core / "hooks").mkdir(parents=True)

    claude_md_content = (
        "# Global Instructions\n\n"
        "## Startup Self-Check\n\n"
        "セッション開始時のチェック内容。\n\n"
        "## Model Tiering\n\n"
        "モデル選択ルール。\n\n"
        "## Output Formatting\n\n"
        "### Markdown Tables\n\n"
        "GFM形式を厳守。\n\n"
        "### Hooks\n\n"
        "- `rtk-rewrite`: Bashコマンドをrtk経由に自動変換\n"
        "- `block-grep-in-bash`: Bashでのgrep/rgを禁止\n"
    )
    (core / "CLAUDE.md").write_text(claude_md_content, encoding="utf-8")
    (core / "RTK.md").write_text("# RTK\n\nToken-optimized CLI proxy.\n", encoding="utf-8")
    (core / "commands.md").write_text("# Commands\n\n| `/demo` | テスト用 |\n", encoding="utf-8")
    (core / "rules" / "core-standards.md").write_text(
        "## コーディング基準\n\n正確さ優先。\n", encoding="utf-8"
    )

    # settings.json テンプレート（settingsSync テスト用）
    (core / "settings.json").write_text(
        json.dumps(
            {
                "env": {"TEMPLATE_ENV": "1"},
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "~/.claude/hooks/demo.sh",
                                }
                            ],
                        }
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    codex_target_dir = root / "packages" / "targets" / "codex"
    codex_target_dir.mkdir(parents=True, exist_ok=True)
    (codex_target_dir / "config.toml").write_text(
        'model = "gpt-5.6"\n'
        '\n'
        '[features]\n'
        'hooks = true\n'
        '\n'
        '[sandbox_workspace_write]\n'
        'writable_roots = [\n'
        '  "~/projects/worktrees",\n'
        '  "~/sandbox/harunon-harness/.git",\n'
        ']\n',
        encoding="utf-8",
    )

    # SKILL.md（frontmatter あり）
    skill_md = (
        "---\n"
        "name: demo-skill\n"
        "description: デモスキル\n"
        "allowed-tools: Bash,Read\n"
        "user-invocable: true\n"
        "---\n"
        "# Demo Skill\n\n"
        "スキルの本文。\n"
    )
    (core / "skills" / "demo-skill" / "SKILL.md").write_text(skill_md, encoding="utf-8")
    # ダミーバイナリ（PNG マジックバイト）
    (core / "skills" / "demo-skill" / "icon.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    )

    # --- targets ---
    def write_config(target: str, cfg: dict) -> None:
        d = root / "packages" / "targets" / target
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    write_config("claude", {
        "name": "claude",
        "displayName": "Claude Code",
        "configDir": "~/.claude",
        "configFile": "settings.json",
        "instructionsFile": "CLAUDE.md",
        "extrasOverlay": True,
        "settingsSync": {
            "source": "packages/core/settings.json",
            "keys": ["hooks"],
        },
        "distribute": {
            "CLAUDE.md": {"source": "packages/core/CLAUDE.md"},
            "RTK.md": {"source": "packages/core/RTK.md"},
            "rules/": {"source": ["packages/core/rules/"]},
            "skills/": {"source": ["packages/core/skills/"]},
        },
    })

    write_config("codex", {
        "name": "codex",
        "displayName": "Codex",
        "configDir": "~/.codex",
        "configFile": "config.toml",
        "instructionsFile": "AGENTS.md",
        "settingsSync": {
            "source": "packages/targets/codex/config.toml",
            "format": "toml",
            "keys": [
                "model",
                "features.hooks",
                "sandbox_workspace_write.writable_roots",
            ],
        },
        "distribute": {
            "AGENTS.md": {
                "source": "packages/core/CLAUDE.md",
            },
            "RTK.md": {"source": "packages/core/RTK.md"},
            "rules/": {"source": ["packages/core/rules/", "packages/extras/_active/rules/"]},
            "skills/": {
                "source": ["packages/core/skills/", "packages/extras/_active/skills/"],
                "transform": "removeClaude専用Frontmatter",
            },
        },
        "skillsTransform": {
            "keepFrontmatterFields": ["name", "description"],
        },
    })

    write_config("opencode", {
        "name": "opencode",
        "displayName": "OpenCode",
        "configDir": "~/.config/opencode",
        "configFile": "",
        "instructionsFile": "AGENTS.md",
        "distribute": {
            "AGENTS.md": {
                "source": "packages/core/CLAUDE.md",
            },
        },
    })

    return root


# ---------------------------------------------------------------------------
# bootstrap.sh テスト用: フェイク distribute.py
# ---------------------------------------------------------------------------

_FAKE_DISTRIBUTE_SOURCE = '''#!/usr/bin/env python3
"""fake distribute.py — テスト用。呼び出し引数を JSON Lines でログするだけ。

BOOTSTRAP_CALL_LOG にログを追記する。
"""
import json
import os
import sys

log_path = os.environ.get("BOOTSTRAP_CALL_LOG")
entry = {"argv": sys.argv[1:]}

if log_path:
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\\n")

sys.exit(int(os.environ.get("FAKE_DISTRIBUTE_EXIT", "0")))
'''


def write_fake_distribute(path: Path) -> None:
    """呼び出し引数を JSON Lines でログするだけのフェイク distribute.py を書き出す。"""
    path.write_text(_FAKE_DISTRIBUTE_SOURCE, encoding="utf-8")


def make_bootstrap_repo(root: Path, with_gitmodules: bool = False, with_extras: bool = True) -> Path:
    """本物の bootstrap.sh + フェイク distribute.py を持つ最小 repo を組み立て、repo_root を返す。

    with_gitmodules=True の場合は .gitmodules を追加する（--skip-submodule の分岐を
    通すため）。宣言された submodule の URL はローカルの存在しないパスなので、
    実際の submodule update は必ずネットワークなしで即時に失敗し、
    bootstrap.sh の skip メッセージ側に落ちる。

    with_extras（デフォルト True）は packages/extras/_active を実際に作成するかどうか。
    extras の有無は bootstrap.sh の fail-close 分岐に影響するため、extras 解決ロジック自体を
    検証する目的以外のテスト（target 順序・dry-run 伝播など）はデフォルトの True のまま
    ノイズなく通す。extras 未取得の挙動を検証するテストのみ False を指定する。
    """
    repo = root / "repo"
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy(str(_SCRIPTS_DIR / "bootstrap.sh"), str(scripts_dir / "bootstrap.sh"))
    write_fake_distribute(scripts_dir / "distribute.py")
    # bootstrap.sh が呼ぶ補助 CLI（codex local config 生成 等）と、それらが import する
    # harness_lib は本物を使う（distribute.py だけフェイク）。
    for helper in (
        "codex-local-config.py",
        "schema_validator.py",
        "mise-global-check.py",
    ):
        shutil.copy(str(_SCRIPTS_DIR / helper), str(scripts_dir / helper))
    shutil.copytree(
        str(_SCRIPTS_DIR / "harness_lib"),
        str(scripts_dir / "harness_lib"),
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    # Step 1.5 (global mise env 確認) が既定パスとして参照する repo ルートの
    # mise.global.example.toml。本物をコピーし、テストは MISE_GLOBAL_CONFIG で
    # live 側だけを差し替える。
    shutil.copy(
        str(_SCRIPTS_DIR.parent / "mise.global.example.toml"),
        str(repo / "mise.global.example.toml"),
    )

    (repo / ".githooks").mkdir()

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    if with_gitmodules:
        (repo / ".gitmodules").write_text(
            "[submodule \"packages/extras/_active\"]\n"
            "\tpath = packages/extras/_active\n"
            "\turl = file:///nonexistent-path-for-test\n",
            encoding="utf-8",
        )

    if with_extras:
        extras = repo / "packages" / "extras" / "_active"
        extras.mkdir(parents=True)
        (extras / "rules").mkdir()

    return repo


def make_extras_skill(repo: Path, skill_name: str, override_content: str) -> None:
    """extras/_active/skills/<skill_name>/SKILL.md を作成する（後勝ちテスト用）。"""
    skill_dir = repo / "packages" / "extras" / "_active" / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(override_content, encoding="utf-8")


def copy_scripts_to_repo(fake_repo: Path) -> None:
    """実際の scripts/ ディレクトリの必要ファイルを fake_repo/scripts/ にコピーする。

    新しい bootstrap.sh は distribute.py を exec するため、
    フィクスチャ repo で bootstrap.sh を動かすには scripts/ 一式が必要。

    コピーするファイル:
      - scripts/distribute.py
      - scripts/harness_lib/ （ディレクトリごと）
    """
    scripts_dst = fake_repo / "scripts"
    scripts_dst.mkdir(exist_ok=True)

    # distribute.py
    shutil.copy(
        str(_SCRIPTS_DIR / "distribute.py"),
        str(scripts_dst / "distribute.py"),
    )

    # schema_validator.py（harness_lib.config が import する）
    shutil.copy(
        str(_SCRIPTS_DIR / "schema_validator.py"),
        str(scripts_dst / "schema_validator.py"),
    )

    # harness_lib/
    harness_lib_src = _SCRIPTS_DIR / "harness_lib"
    harness_lib_dst = scripts_dst / "harness_lib"
    if harness_lib_dst.exists():
        shutil.rmtree(str(harness_lib_dst))
    shutil.copytree(str(harness_lib_src), str(harness_lib_dst))

    # schemas/（target_config_errors 等が必須の契約として要求する）
    schemas_src = _SCRIPTS_DIR.parent / "schemas"
    schemas_dst = fake_repo / "schemas"
    if schemas_dst.exists():
        shutil.rmtree(str(schemas_dst))
    shutil.copytree(str(schemas_src), str(schemas_dst))
