#!/usr/bin/env python3
"""Claude Code のセッションログから「人が始めた作業」だけを数える。

cclens のセッション数は hook が自動起動したセッションを含むため、
利用実態の報告にそのまま使うと水増しになる。ここで自動分を落とす。

日付は `--tz`（既定 Asia/Tokyo）のローカル日付で扱う。ログの timestamp は UTC なので、
変換しないと月末・月初のセッションが隣の月に落ちる。

  python3 sessions.py --since 2026-07-16
  python3 sessions.py --since 2026-07-16 --repos my-app,my-docs  # worktree を repo に畳む
  python3 sessions.py --since 2026-07-16 --list                  # 1行1セッションの生出力

検証は scripts/tests/test_ai_usage_report.py（run-tests.py が拾う）。
"""

import argparse
import collections
import glob
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

PROJECTS = os.path.expanduser("~/.claude/projects/*/*.jsonl")
# Claude Code は cwd の `/` と `.` を `-` に潰してディレクトリ名にする
HOME_DIR = re.sub(r"[/.]", "-", os.path.expanduser("~"))

# hook が自動投入するセッション冒頭。人の作業として数えない。
AUTO_OPENERS = (
    "Review this change for security vulnerabilities.",
    "The user just ran /insights",
)

CATEGORIES = (
    ("PR/GitHub操作", r"github\.com/\S+/pull/|conflict|マージ|プルリク"),
    ("CI/ビルド/環境", r"actions/runs|workflow|netlify|deprecated|pnpm|mise|volta|eslint"),
    ("設定/harness整備", r"sync-settings|harness|hook|settings|sandbox|cclens|OTEL"),
    ("レビュー", r"敵対的評価|レビュー|review"),
    ("issue tracker 起点", r"linear\.app|/issues?/\d"),
    ("UI/デザイン", r"figma|デザイン|storybook|見た目|余白"),
    ("調査・相談", r"[?？]|なんで|教えて|どう|べき"),
)


def repo_of(project_dir, repos):
    """プロジェクトディレクトリ名を repo 単位に畳む。

    `--repos` を渡すと worktree ディレクトリも元 repo にまとまる。
    渡さなければ home prefix を落としたディレクトリ名をそのまま使う。

    名前が被る指定（`app,app-docs`）で引数の順に結果が変わらないよう、
    一致した中で最長のものを採る。
    """
    matched = [name for name in repos if name in project_dir]
    if matched:
        return max(matched, key=len)
    if project_dir == HOME_DIR:
        return "home(調査/相談)"
    return project_dir.replace(HOME_DIR + "-", "", 1)


def classify(opener):
    """セッション冒頭から作業種別を返す。(is_auto, category)"""
    if opener.startswith(AUTO_OPENERS):
        return True, "自動(hook)"
    skill = re.match(r"Base directory for this skill: \S*/skills/([\w:-]+)", opener)
    if skill:
        return False, f"skill:{skill.group(1)}"
    for name, pattern in CATEGORIES:
        if re.search(pattern, opener, re.I):
            return False, name
    return False, "その他"


def first_prompt(path):
    """セッション最初の人間の発話と timestamp。無ければ (None, None)。"""
    with open(path, errors="replace") as fh:
        for line in fh:
            if '"type":"user"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "user" or d.get("isSidechain"):
                continue
            content = d.get("message", {}).get("content")
            if isinstance(content, list):
                content = "".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            if not isinstance(content, str):
                continue
            text = content.strip()
            # システム注入・コマンド出力・再開時のメタ発話は人の指示ではない
            if not text or text[0] == "<" or text.startswith(("Caveat", "[Request")):
                continue
            return text.replace("\n", " ")[:200], d.get("timestamp", "")
    return None, None


def local_date(ts, tz):
    """UTC の ISO timestamp を報告先タイムゾーンの YYYY-MM-DD にする。

    変換せず `ts[:10]` で切ると、JST の 10/1 未明が UTC ではまだ 9/30 なので
    `--since` も月別集計も隣の月にずれる。
    """
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz).strftime("%Y-%m-%d")


def collect(since, repos, tz):
    rows = []
    for path in glob.glob(PROJECTS):
        try:
            opener, ts = first_prompt(path)
        except OSError:
            continue
        if not opener or not ts:
            continue
        try:
            date = local_date(ts, tz)
        except ValueError:
            continue
        if date < since:
            continue
        is_auto, category = classify(opener)
        rows.append(
            {
                "date": date,
                "repo": repo_of(os.path.basename(os.path.dirname(path)), repos),
                "auto": is_auto,
                "category": category,
                "opener": opener,
            }
        )
    rows.sort(key=lambda r: r["date"])
    return rows


def report(rows):
    human = [r for r in rows if not r["auto"]]
    auto = len(rows) - len(human)
    print(f"人が始めたセッション {len(human)} / 自動(hook) {auto} / 合計 {len(rows)}")

    for title, key in (("repo別", "repo"), ("作業種別", "category"), ("月別", "date")):
        print(f"\n-- {title}")
        counter = collections.Counter(
            r[key][:7] if key == "date" else r[key] for r in human
        )
        items = sorted(counter.items()) if key == "date" else counter.most_common()
        for name, count in items:
            print(f"  {count:4d}  {name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="1970-01-01", help="YYYY-MM-DD")
    parser.add_argument("--repos", default="", help="worktree を畳む repo 名（カンマ区切り）")
    parser.add_argument("--tz", default="Asia/Tokyo", help="日付を解釈するタイムゾーン")
    parser.add_argument("--list", action="store_true", help="1行1セッションで生出力")
    args = parser.parse_args()

    repos = [r for r in args.repos.split(",") if r]
    rows = collect(args.since, repos, ZoneInfo(args.tz))
    if args.list:
        for r in rows:
            flag = "auto" if r["auto"] else "人"
            print(f"{r['date']} | {flag} | {r['repo']} | {r['category']} | {r['opener']}")
        return
    report(rows)


if __name__ == "__main__":
    main()
