"""常駐コンテキストの予算（常時ロード文書・target 別 AGENTS.md + skill frontmatter）。"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import target_config_paths
from ..curated_skills import list_curated_skills
from ..frontmatter import FRONTMATTER_BLOCK_RE, has_paths_frontmatter
from ..resolver import manifest
from ..validator_registry import Finding

# 固定コンテキスト予算（bytes、4 chars ≈ 1 token の概算換算）。
# 2026-07-02 実測: CLAUDE.md + RTK.md + rules/*.md が毎セッション（HEADROOM.md は 2026-07-11 に常駐外し）
# 注入される（`alwaysApply: false` は効かず、`paths:` frontmatter によるプロジェクト
# スコープのみが注入を防ぐ）。warn は「そろそろ削減を検討すべき」ライン、
# error は「セッション開始コストが無視できない」ライン。
ALWAYS_LOADED_WARN_BYTES = 40_000
ALWAYS_LOADED_ERROR_BYTES = 48_000


def check_always_loaded_budget(repo_root: Path) -> list[Finding]:
    """常時ロード文書（CLAUDE.md + RTK.md + rules/*.md）の
    合計バイト数が固定コンテキスト予算を超えていないか検証する。

    skill frontmatter はこの関数の対象外で、claude を含む全ターゲットぶんを
    check_target_residency_budget が別枠で見る（2026-09-11 まで claude だけ
    どちらの予算からも漏れており、harness 所有分 9,184 文字が無検証で
    常駐していた）。

    HEADROOM.md は 2026-07-11 に @参照を外して on-demand 化したため対象外
    （実測未使用: headroom プロセスなし・全プロジェクト ANTHROPIC_BASE_URL 未設定）。
    `paths:` frontmatter でプロジェクトスコープされた rules（例:
    oss-contribution.md）は対象外プロジェクトでは注入されないため除外する。
    """
    core = repo_root / "packages" / "core"
    rules_dir = core / "rules"
    targets = [core / "CLAUDE.md", core / "RTK.md"]
    if rules_dir.is_dir():
        targets.extend(sorted(rules_dir.glob("*.md")))

    total = 0
    for path in targets:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if path.parent == rules_dir and has_paths_frontmatter(text):
            continue
        total += len(text.encode("utf-8"))

    if total <= ALWAYS_LOADED_WARN_BYTES:
        return []

    level = "error" if total > ALWAYS_LOADED_ERROR_BYTES else "warn"
    return [
        Finding(
            check="always-loaded-budget",
            level=level,
            message=(
                f"常時ロード文書の合計が {total:,} bytes "
                f"（warn: {ALWAYS_LOADED_WARN_BYTES:,} / error: {ALWAYS_LOADED_ERROR_BYTES:,}）"
            ),
        )
    ]


# 各ターゲットの常駐予算（AGENTS.md 本文 + skill frontmatter 合計）。
# 2026-07-11 実測（今日の再構築で達成した常駐トークン最小の状態を機械的に維持する
# ため）: codex AGENTS.md=2041 chars / frontmatter 合計=7264 chars、
# omp AGENTS.md=2219 / 7264、pi AGENTS.md=2300 / 7264、
# opencode AGENTS.md=3351 / 7429（G1 対応後）。claude は AGENTS.md を配布しない
# （CLAUDE.md が相当し check_always_loaded_budget が見る）ので frontmatter だけが
# 検証される。warn は予算の 90%、error は skill 追加や AGENTS.md
# 肥大の入れ忘れをブロックするライン。
TARGET_AGENTS_MD_ERROR_CHARS = 4_500
TARGET_AGENTS_MD_WARN_CHARS = int(TARGET_AGENTS_MD_ERROR_CHARS * 0.9)

# runtime が AGENTS.md を読み込む物理上限（bytes）。超過分は runtime 側で無言に切り捨て
# られ、指示が途中で消える。上の文字数予算は「常駐コストを抑える」線で、こちらは
# 「読まれなくなる」線。予算の方がずっと手前にあるので通常はこちらに当たらないが、
# 予算を緩めたときにこの天井を越えないよう別枠で error にする。runtime 側の設定で
# 上限を引き上げる案は採らない（AGENTS.md を減らすのが正で、上限を上げるのは常駐
# コストを増やすだけ）。codex: project_doc_max_bytes の既定 32 KiB。他 runtime は
# 同種の上限を公表していないため未登録。
PROJECT_DOC_HARD_LIMIT_BYTES = {"codex": 32 * 1024}
TARGET_FRONTMATTER_ERROR_CHARS = 9_000
TARGET_FRONTMATTER_WARN_CHARS = int(TARGET_FRONTMATTER_ERROR_CHARS * 0.9)

# claude は harness 所有 skill を 36 本配布する（他ターゲットは codex 2 本のように
# 数本）ため、共通の 9,000 は構成差を無視した線になる。2026-09-11 実測 9,184 文字。
# warn=9,000 は「現状が既に重い」ことを可視化する線（今まさに超えている）、
# error=11,000 は skill 追加で青天井に増えるのを止める線。frontmatter の削減自体は
# 別タスクで、ここは検証対象に入れることが目的。
CLAUDE_FRONTMATTER_ERROR_CHARS = 11_000
CLAUDE_FRONTMATTER_WARN_CHARS = 9_000

# skills/<name>/SKILL.md 形式（直下のみ、ネストされた skill は対象外）
_SKILL_MD_DIRECT_RE = re.compile(r"^skills/[^/]+/SKILL\.md$")


def agents_md_findings(target_name: str, agents_bytes: bytes) -> list[Finding]:
    """配布される AGENTS.md（include 展開後）を、常駐予算（文字数）と runtime の
    読み込み上限（bytes）の 2 本で検証する。"""
    findings: list[Finding] = []
    agents_chars = len(agents_bytes.decode("utf-8"))
    if agents_chars > TARGET_AGENTS_MD_WARN_CHARS:
        level = "error" if agents_chars > TARGET_AGENTS_MD_ERROR_CHARS else "warn"
        findings.append(
            Finding(
                check="target-residency-budget",
                level=level,
                message=(
                    f"{target_name}: AGENTS.md が {agents_chars:,} 文字 "
                    f"（warn: {TARGET_AGENTS_MD_WARN_CHARS:,} / "
                    f"error: {TARGET_AGENTS_MD_ERROR_CHARS:,}）"
                ),
            )
        )
    hard_limit = PROJECT_DOC_HARD_LIMIT_BYTES.get(target_name)
    if hard_limit is not None and len(agents_bytes) >= hard_limit:
        findings.append(
            Finding(
                check="project-doc-hard-limit",
                level="error",
                message=(
                    f"{target_name}: AGENTS.md が {len(agents_bytes):,} bytes で runtime の"
                    f"読み込み上限 {hard_limit:,} bytes に達している（超過分は無言で"
                    f"切り捨てられる）。上限を上げずに AGENTS.md を減らす"
                ),
            )
        )
    return findings


def check_target_residency_budget(repo_root: Path) -> list[Finding]:
    """各ターゲットの常駐予算（AGENTS.md + skill frontmatter 合計）を検証する。

    harness_lib.resolver.manifest() は target 別 transform（skillsTransform 等）
    適用後の実配布内容を返すため、実際にそのターゲットのセッションへ常駐する
    バイト数をそのまま検証できる。skill 追加や AGENTS.md 肥大を入れ忘れたまま
    push すると ERROR で止める。

    manifest() は extras submodule 未取得環境でも動作する（warnings が出るだけ）。
    CI 等で未取得の場合 frontmatter 合計が実測より小さくなり得るが、予算は
    上限チェックのため過小評価は問題にならない。
    """
    findings: list[Finding] = []
    for config_path in target_config_paths(repo_root):
        target_name = config_path.parent.name
        try:
            m = manifest(target_name, repo_root)
        except (FileNotFoundError, ValueError) as e:
            findings.append(
                Finding(
                    check="target-residency-budget",
                    level="error",
                    message=f"{target_name}: manifest 解決に失敗: {e}",
                )
            )
            continue

        agents_bytes = m.files.get("AGENTS.md")
        if agents_bytes is not None:
            findings.extend(agents_md_findings(target_name, agents_bytes))

        # curated（rulesync upstream）skill は ledger 管理下に入ったが、frontmatter の
        # 大きさは harness が制御できない。予算は harness 所有分の肥大を止める線なので
        # 除外する（予算値 9,000 は curated を数えていなかった 2026-07-11 実測が基準）。
        curated = list_curated_skills(repo_root)
        frontmatter_total = 0
        for rel, content in m.files.items():
            if not _SKILL_MD_DIRECT_RE.match(rel):
                continue
            if rel.split("/")[1] in curated:
                continue
            fm_match = FRONTMATTER_BLOCK_RE.match(content.decode("utf-8"))
            if fm_match:
                frontmatter_total += len(fm_match.group(0))

        if target_name == "claude":
            warn_chars = CLAUDE_FRONTMATTER_WARN_CHARS
            error_chars = CLAUDE_FRONTMATTER_ERROR_CHARS
        else:
            warn_chars = TARGET_FRONTMATTER_WARN_CHARS
            error_chars = TARGET_FRONTMATTER_ERROR_CHARS

        if frontmatter_total > warn_chars:
            level = "error" if frontmatter_total > error_chars else "warn"
            findings.append(
                Finding(
                    check="target-residency-budget",
                    level=level,
                    message=(
                        f"{target_name}: skill frontmatter 合計が "
                        f"{frontmatter_total:,} 文字（warn: "
                        f"{warn_chars:,} / error: {error_chars:,}）"
                    ),
                )
            )

    return findings


CHECKS = {
    "always-loaded-budget": check_always_loaded_budget,
    "target-residency-budget": check_target_residency_budget,
}
