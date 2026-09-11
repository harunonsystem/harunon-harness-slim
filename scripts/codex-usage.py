#!/usr/bin/env python3
"""~/.codex の rollout ログから Codex の実消費を集計し、どのセッションが枠を溶かしたか出す。

Codex のレート枠は出力でもモデルでもなく「入力の再送」で溶ける。実測では消費の 99% 以上が
input で、その 95% が cached input（= 同じ文脈の読み直し）だった。つまり削る対象は
セッションの寿命であって、reasoning effort や渡し方の圧縮ではない。

この集計はそれを経路別・ターン数帯別に見せて「どのセッションを切るべきか」を決めるためのもの。
効果測定にも使う（設定や運用を変えた後、--since で前後を比べる）。

「ターン数」は rollout に記録された token_count イベントの数、つまりモデル呼び出し回数の
近似で、人間の発話回数より多く出る。1 ターンあたりの単価を帯域で比べるために使う。

model × effort 別も出す。低い effort は 1 ターンが安い代わりに試行回数が増えるため、
「安い effort ほど安いセッションになる」とは限らない。どの組み合わせが自分の使い方で
安いかはモデルごとに違うので、値の解釈は ADR-010 / model-routing.json 側に置き、
ここは材料だけを出す。

effort 別を比べるときは交絡に注意する。effort はタスクの難易度に応じて選ばれるので、
「高い effort のセッションが短い」ことは effort の効果とは限らない。同じ種類の作業で
effort だけを変えた比較でなければ因果は言えない。

exit code:
  0  集計して表示した
  2  rollout ログが見つからなかった（Codex 未使用 / CODEX_HOME の指定違い）
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import sys

# ターン数の帯域。25 を超えると 1 ターンの単価が倍になる（2026-09 実測）ため境界を細かく置く。
TURN_BANDS = (10, 25, 50, 100, 200, 400, 800)

# パレートを打つ位置。上位 10 セッションで全体の 47% だった（2026-09 実測）ので上側を細かく見る。
PARETO_MARKS = (1, 5, 10, 20, 50, 100)


@dataclass
class Session:
    """1 rollout = 1 Codex セッションの累積消費。

    生成するのは parse_rollout だけで、token_usage を 1 件以上持つログしか Session にしない。
    したがって turns >= 1 が保証され、集計側は 0 除算を防ぐ必要がない。
    """

    path: Path
    date: str
    originator: str
    total: int
    input_tokens: int
    cached: int
    output: int
    reasoning: int
    turns: int
    # セッション途中で picker を触ると変わるため、最後に見た組み合わせを代表値にする。
    model: str = "(unknown)"
    effort: str = "(unset)"
    # session_meta.thread_source。user（親）/ subagent / guardian_review を分ける軸。
    thread_source: str = "(none)"
    rate_limits: dict = field(default_factory=dict)


def find_rollouts(codex_home: Path) -> list[Path]:
    """sessions/ と archived_sessions/ の rollout ログを集める。

    archived を含めるのは、Codex が古いセッションをそちらへ移すため。除くと過去の
    重いセッションが消えて「今月は軽い」と読み違える。
    """
    return sorted(codex_home.glob("sessions/**/rollout-*.jsonl")) + sorted(
        codex_home.glob("archived_sessions/rollout-*.jsonl")
    )


def parse_rollout(path: Path) -> Session | None:
    """rollout 1 本を読んで累積消費を返す。token_usage か開始時刻を欠くログは None。

    total_token_usage は行ごとに累積値を持つので最大値を取る。最終行を使わないのは、
    セッションが中断されたログでは末尾に usage が来ないことがあるため。

    全行に json.loads を掛けると重いので、必要なキーを含む行だけを対象にする。
    """
    originator = ""
    started_at = ""
    thread_source = ""
    model = ""
    effort = ""
    turns = 0
    best: dict = {}
    rate_limits: dict = {}

    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not originator and '"session_meta"' in line:
                meta = _payload(line)
                originator = meta.get("originator", "")
                started_at = meta.get("timestamp", "")
                thread_source = meta.get("thread_source", "")
            if '"turn_context"' in line:
                context = _payload(line)
                model = context.get("model") or model
                effort = context.get("effort") or effort
            if '"total_token_usage"' not in line:
                continue
            payload = _payload(line)
            usage = (payload.get("info") or {}).get("total_token_usage") or {}
            if usage.get("total_tokens") is None:
                continue
            turns += 1
            if usage["total_tokens"] >= best.get("total_tokens", -1):
                best = usage
            if payload.get("rate_limits"):
                rate_limits = payload["rate_limits"]

    if not best or not started_at:
        return None
    return Session(
        path=path,
        date=started_at[:10],
        originator=originator or "(unknown)",
        total=best["total_tokens"],
        input_tokens=best.get("input_tokens", 0),
        cached=best.get("cached_input_tokens", 0),
        output=best.get("output_tokens", 0),
        reasoning=best.get("reasoning_output_tokens", 0),
        turns=turns,
        model=model or "(unknown)",
        effort=effort or "(unset)",
        thread_source=thread_source or "(none)",
        rate_limits=rate_limits,
    )


def _payload(line: str) -> dict:
    try:
        return json.loads(line).get("payload") or {}
    except (json.JSONDecodeError, AttributeError):
        return {}


def turn_band(turns: int) -> str:
    """ターン数を帯域ラベルにする。ソート可能な形にするため上限値で桁を揃える。"""
    for limit in TURN_BANDS:
        if turns <= limit:
            return f"<={limit:5d} turns"
    return f" >{TURN_BANDS[-1]:4d} turns"


def _group(sessions: list[Session], key: Callable[[Session], object]) -> dict:
    """key ごとに Session をまとめる。経路別・帯域別・model×effort 別が同じ形を使う。"""
    grouped: dict = {}
    for session in sessions:
        grouped.setdefault(key(session), []).append(session)
    return grouped


def by_originator(sessions: list[Session]) -> list[tuple[str, int, int, int]]:
    """経路（originator）別に (名前, セッション数, 総消費, 1 セッション平均) を消費順で返す。"""
    rows = []
    for name, items in _group(sessions, lambda s: s.originator).items():
        total = sum(s.total for s in items)
        rows.append((name, len(items), total, total // len(items)))
    return sorted(rows, key=lambda row: -row[2])


def pareto_rows(sessions: list[Session]) -> list[tuple[int, int, float]]:
    """重い順に累積して (セッション数, 累積消費, 全体比) を返す。消費の集中度を見るため。"""
    ordered = sorted(sessions, key=lambda s: -s.total)
    grand = sum(s.total for s in ordered)
    if grand == 0:
        return []
    marks = [m for m in PARETO_MARKS if m < len(ordered)] + [len(ordered)]
    rows = []
    acc = 0
    for index, session in enumerate(ordered, 1):
        acc += session.total
        if index in marks:
            rows.append((index, acc, acc * 100.0 / grand))
    return rows


def band_rows(sessions: list[Session]) -> list[tuple[str, int, int, int]]:
    """ターン数帯ごとに (帯域, セッション数, 総消費, 1 ターン平均) を返す。

    1 ターン平均が帯域とともに上がるなら、セッションを長く続けること自体が単価を
    上げている（文脈が満杯に近づき毎ターン再送する量が増える）。
    """
    rows = []
    for band, items in sorted(_group(sessions, lambda s: turn_band(s.turns)).items()):
        total = sum(s.total for s in items)
        rows.append((band, len(items), total, total // sum(s.turns for s in items)))
    return rows


def by_model_effort(sessions: list[Session]) -> list[tuple[str, str, int, float, int, int, int]]:
    """model × effort 別に (model, effort, セッション数, turns/sess, 1セッション平均, tok/turn, 総消費)。

    見るべきは 1 セッション平均で、tok/turn ではない。1 ターンの単価が高い組み合わせでも、
    試行回数が少なければセッション単位では安くなる。総消費順に並べて、実際に使い込んだ
    組み合わせが上に来るようにする（1〜2 セッションだけの組み合わせは参考外）。
    """
    rows = []
    for (model, effort), items in _group(sessions, lambda s: (s.model, s.effort)).items():
        total = sum(s.total for s in items)
        turns = sum(s.turns for s in items)
        rows.append(
            (model, effort, len(items), turns / len(items), total // len(items), total // turns, total)
        )
    return sorted(rows, key=lambda row: -row[6])


def by_thread_source(sessions: list[Session]) -> list[tuple[str, int, float, int, int, float, int]]:
    """thread_source 別に (source, セッション数, turns/sess, 1セッション平均, tok/turn, cached率, 総消費)。

    親（user）と subagent を分けて見るための軸。subagent は fresh context で始まるから軽い、という
    直感は 2026-09-10 の実測では成り立たなかった（cached 率は親とほぼ同じで、1 ターンは親より高い）。
    親から渡る handoff の大きさが効くため、subagent を増やせば安くなるとは限らない。

    thread_source を持たない古い rollout は "(none)" に落ちる。世代混在の集計を親子比較として
    読まないよう、件数を見て判断すること。
    """
    rows = []
    for source, items in _group(sessions, lambda s: s.thread_source).items():
        total = sum(s.total for s in items)
        turns = sum(s.turns for s in items)
        inputs = sum(s.input_tokens for s in items)
        cached_rate = sum(s.cached for s in items) * 100.0 / inputs if inputs else 0.0
        rows.append(
            (source, len(items), turns / len(items), total // len(items), total // turns, cached_rate, total)
        )
    return sorted(rows, key=lambda row: -row[6])


def report(sessions: list[Session], top: int) -> None:
    grand = sum(s.total for s in sessions)
    output = sum(s.output for s in sessions)
    reasoning = sum(s.reasoning for s in sessions)
    print(f"対象 {len(sessions)} セッション / 総計 {grand:,} トークン")
    print(
        f"  input {sum(s.input_tokens for s in sessions):,}"
        f"（うち cached {sum(s.cached for s in sessions):,}）"
        f"  output {output:,}"
        f"  reasoning {reasoning:,}"
        + (f"（output の {reasoning * 100.0 / output:.0f}%）" if output else "")
    )

    print("\n=== 経路別（どこが枠を食っているか） ===")
    for name, count, total, avg in by_originator(sessions):
        share = f" ({total * 100.0 / grand:5.1f}%)" if grand else ""
        print(f"{name[:22]:22s} sessions={count:4d}  total={total:14,}{share}  1セッション平均={avg:12,}")

    print("\n=== パレート（重い順に累積） ===")
    for count, acc, share in pareto_rows(sessions):
        print(
            f"上位 {count:4d} セッション ({count * 100.0 / len(sessions):5.1f}%)"
            f"  累積 {acc:14,}  = 全体の {share:5.1f}%"
        )

    print("\n=== ターン数帯ごとの 1 ターン平均（長いセッションの単価） ===")
    for band, count, total, per_turn in band_rows(sessions):
        print(f"{band}  sessions={count:4d}  total={total:14,}  1ターン平均={per_turn:9,}")

    print("\n=== thread_source 別（親 user と subagent を分ける。(none) は古い世代） ===")
    print(f"{'source':16s} {'sess':>5s} {'turns/sess':>10s} {'1セッション平均':>16s} {'tok/turn':>10s} {'cached率':>8s}")
    for source, count, per_sess, per_session_total, per_turn, cached_rate, _ in by_thread_source(sessions):
        print(
            f"{source[:16]:16s} {count:5d} {per_sess:10.1f}"
            f" {per_session_total:16,} {per_turn:10,} {cached_rate:7.1f}%"
        )

    print("\n=== model × effort 別（effort を上げると試行回数が減る。見るのは 1セッション平均） ===")
    print(f"{'model':20s} {'effort':8s} {'sess':>5s} {'turns/sess':>10s} {'1セッション平均':>16s} {'tok/turn':>10s}")
    for model, effort, count, per_sess, per_session_total, per_turn, _ in by_model_effort(sessions):
        print(
            f"{model[:20]:20s} {effort[:8]:8s} {count:5d} {per_sess:10.1f}"
            f" {per_session_total:16,} {per_turn:10,}"
        )

    print(f"\n=== 重いセッション上位 {top} ===")
    for session in sorted(sessions, key=lambda s: -s.total)[:top]:
        print(
            f"{session.date}  {session.total:12,}  turns={session.turns:4d}"
            f"  {session.model[:16]:16s} {session.effort[:6]:6s}"
            f"  {session.originator[:14]:14s} {session.path.name}"
        )

    latest = [s for s in sessions if s.rate_limits]
    if latest:
        print("\n=== 直近の枠の使用率（rollout に記録された最新のもの） ===")
        for session in sorted(latest, key=lambda s: s.date, reverse=True)[:5]:
            limits = session.rate_limits
            primary = limits.get("primary") or {}
            secondary = limits.get("secondary") or {}
            credits = limits.get("credits") or {}
            print(
                f"{session.date}  5h窓={primary.get('used_percent')}%"
                f"  週窓={secondary.get('used_percent')}%"
                f"  plan={limits.get('plan_type')}"
                f"  credits={credits.get('has_credits')}"
                f"  reached={limits.get('rate_limit_reached_type')}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"),
        help="rollout ログを探す Codex home（既定: $CODEX_HOME か ~/.codex）",
    )
    parser.add_argument("--since", help="この年月以降だけ集計する（例: 2026-09）")
    parser.add_argument("--top", type=int, default=10, help="重いセッションの表示件数（既定: 10）")
    args = parser.parse_args()

    rollouts = find_rollouts(args.codex_home)
    if not rollouts:
        print(f"rollout ログが見つかりませんでした: {args.codex_home}")
        return 2

    parsed = [s for s in (parse_rollout(path) for path in rollouts) if s is not None]
    sessions = [s for s in parsed if s.date >= args.since] if args.since else parsed
    if not sessions:
        print(f"集計対象のセッションがありませんでした（rollout {len(rollouts)} 本、--since {args.since}）")
        return 2

    # 脱落を黙って捨てない。差分は usage 記録前に終わったセッション。
    print(f"rollout {len(rollouts)} 本 / 消費記録あり {len(parsed)} 本")
    report(sessions, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
