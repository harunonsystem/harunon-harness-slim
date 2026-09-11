#!/usr/bin/env python3
"""Harness メタ情報の整合性を検証する。

Usage:
    validate-harness.py [--repo-root PATH] [--json]

各 check の実体は scripts/harness_lib/validators/ 配下（1 モジュール = 1 関心事）。
実行順は harness_lib.validators.CHECKS が決める。ここは argparse と出力整形だけを持つ
thin CLI。

Checks:
    - packages/targets/*/config.json の distribute source 実在
    - portable な rules / shared・target Agents.md 内への ledger model id 混入と routing projection の socket 宣言
    - commands.md に記載された slash command と skills/ の対応（双方向）
    - SKILL.md の casing / frontmatter
    - settings.json の hook 配線 ↔ hooks/ 実ファイル
    - CONTEXT.md の管理規模カウント
    - CONTEXT.md「ツール間の差異」表の列 ↔ packages/targets/ 実ディレクトリの一致
    - 常時ロード文書（CLAUDE.md + RTK.md + rules/*.md）の固定コスト予算
    - claude 以外の各ターゲットの常駐予算（AGENTS.md + skill frontmatter 合計）
    - rules/*.md と CLAUDE.md 内の `/skill` 参照の実在
    - agents/*.md・skills/*/SKILL.md・CLAUDE.md・commands.md 内の `rules/<name>.md` パス参照の実在
    - SKILL.md frontmatter の `references:` パスの実在
    - core の skills/rules にプロジェクト固有コンテンツが混入していないか
    - vendored スキルの NOTICE.txt に再配布禁止の記載がないか（警告）
    - docs/plans/README.md 索引 ↔ plan frontmatter の status 一致
    - capability-contract.json の runtime target / dimension parity と static evidence
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

# harness_lib は scripts/ 配下にあるため sys.path を調整する
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from harness_lib.runtime import require_supported_python  # noqa: E402

require_supported_python()

from harness_lib.validators import run_checks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate harunon-harness meta consistency")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument("--json", action="store_true", help="Output findings as JSON")
    args = parser.parse_args()

    findings = run_checks(args.repo_root)
    n_errors = sum(1 for f in findings if f.level == "error")
    n_warns = sum(1 for f in findings if f.level == "warn")

    if args.json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        for finding in findings:
            prefix = "ERROR" if finding.level == "error" else "WARN"
            label = finding.check
            if finding.code is not None:
                label += f"({finding.code})"
            print(f"[{prefix}] {label}: {finding.message}")
        if not findings:
            print("OK: all meta checks passed")
        else:
            print(f"\nSummary: {n_errors} error(s), {n_warns} warning(s)")

    return 1 if n_errors else 0


if __name__ == "__main__":
    sys.exit(main())
