"""Codex rollout ログの消費集計（経路別・パレート・ターン数帯）。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_spec = importlib.util.spec_from_file_location("codex_usage", REPO_ROOT / "scripts" / "codex-usage.py")
codex_usage = importlib.util.module_from_spec(_spec)
sys.modules["codex_usage"] = codex_usage
_spec.loader.exec_module(codex_usage)


def session(
    total: int,
    turns: int = 1,
    originator: str = "Codex Desktop",
    date: str = "2026-09-01",
    model: str = "gpt-5.6-sol",
    effort: str = "medium",
    thread_source: str = "user",
    cached: int = 0,
):
    return codex_usage.Session(
        path=Path(f"rollout-{total}.jsonl"),
        date=date,
        originator=originator,
        total=total,
        input_tokens=total,
        cached=cached,
        output=0,
        reasoning=0,
        turns=turns,
        model=model,
        effort=effort,
        thread_source=thread_source,
    )


def usage_line(total: int, **extra) -> str:
    usage = {"total_tokens": total, "input_tokens": total, "output_tokens": 0}
    return json.dumps({"type": "event_msg", "payload": {"info": {"total_token_usage": usage}, **extra}})


def meta_line(
    originator: str = "Codex Desktop",
    timestamp: str = "2026-09-01T00:00:00Z",
    thread_source: str = "user",
) -> str:
    payload = {"originator": originator}
    if timestamp:
        payload["timestamp"] = timestamp
    if thread_source:
        payload["thread_source"] = thread_source
    return json.dumps({"type": "session_meta", "payload": payload})


def rollout(tmp: str, name: str, *lines: str) -> Path:
    """rollout ログを 1 本書いてパスを返す。parse_rollout の入力を組むための土台。"""
    path = Path(tmp) / name
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestTurnBand(unittest.TestCase):
    def test_boundaries_are_inclusive(self):
        self.assertEqual(codex_usage.turn_band(10), codex_usage.turn_band(1))
        self.assertNotEqual(codex_usage.turn_band(10), codex_usage.turn_band(11))

    def test_beyond_last_band_is_open_ended(self):
        self.assertIn(">", codex_usage.turn_band(5000))


class TestByOriginator(unittest.TestCase):
    def test_sorted_by_total_desc_with_average(self):
        rows = codex_usage.by_originator(
            [session(100, originator="Codex Desktop"), session(300, originator="Codex Desktop"), session(50, originator="Claude Code")]
        )
        self.assertEqual(("Codex Desktop", 2, 400, 200), rows[0])
        self.assertEqual(("Claude Code", 1, 50, 50), rows[1])


class TestPareto(unittest.TestCase):
    def test_accumulates_heaviest_first(self):
        rows = codex_usage.pareto_rows([session(10), session(90)])
        # 2 セッションなので打点は「上位 1」と全体の 2 つ。
        self.assertEqual(2, len(rows))
        self.assertEqual((1, 90, 90.0), rows[0])
        self.assertEqual((2, 100, 100.0), rows[1])

    def test_empty_consumption_is_not_divided(self):
        self.assertEqual([], codex_usage.pareto_rows([session(0)]))


class TestBandRows(unittest.TestCase):
    def test_per_turn_is_total_over_turns(self):
        rows = codex_usage.band_rows([session(1000, turns=10), session(1000, turns=10)])
        self.assertEqual(1, len(rows))
        _, count, total, per_turn = rows[0]
        self.assertEqual((2, 2000, 100), (count, total, per_turn))


class TestByModelEffort(unittest.TestCase):
    def test_groups_by_pair_and_reports_per_session(self):
        rows = codex_usage.by_model_effort(
            [
                session(1000, turns=10, effort="medium"),
                session(3000, turns=20, effort="medium"),
                session(500, turns=2, effort="xhigh"),
            ]
        )
        model, effort, count, per_sess, per_session_total, per_turn, total = rows[0]
        self.assertEqual(("gpt-5.6-sol", "medium", 2), (model, effort, count))
        self.assertEqual(15.0, per_sess)
        self.assertEqual(2000, per_session_total)
        # 1 ターン単価は総消費 / 総ターン数（4000 / 30）。
        self.assertEqual(133, per_turn)
        self.assertEqual(4000, total)
        self.assertEqual("xhigh", rows[1][1])

    def test_sorted_by_total_desc(self):
        rows = codex_usage.by_model_effort([session(10, effort="low"), session(90, effort="max")])
        self.assertEqual(["max", "low"], [row[1] for row in rows])


class TestByThreadSource(unittest.TestCase):
    def test_separates_parent_from_subagent_with_cached_rate(self):
        rows = codex_usage.by_thread_source(
            [
                session(1000, turns=10, thread_source="user", cached=900),
                session(400, turns=2, thread_source="subagent", cached=200),
            ]
        )
        source, count, per_sess, per_session_total, per_turn, cached_rate, total = rows[0]
        self.assertEqual(("user", 1, 10.0, 1000, 100, 1000), (source, count, per_sess, per_session_total, per_turn, total))
        self.assertAlmostEqual(90.0, cached_rate)
        self.assertEqual("subagent", rows[1][0])
        # subagent 側は cached 200 / input 400。
        self.assertAlmostEqual(50.0, rows[1][5])

    def test_zero_input_does_not_divide_by_zero(self):
        # total_token_usage に input_tokens が無い古いログは input 0 になりうる。
        blank = codex_usage.Session(
            path=Path("rollout-blank.jsonl"),
            date="2026-09-01",
            originator="codex-tui",
            total=5,
            input_tokens=0,
            cached=0,
            output=0,
            reasoning=0,
            turns=1,
        )
        self.assertEqual(0.0, codex_usage.by_thread_source([blank])[0][5])

    def test_missing_thread_source_falls_back_to_none_bucket(self):
        rows = codex_usage.by_thread_source([session(10, thread_source="(none)")])
        self.assertEqual("(none)", rows[0][0])


class TestParseRollout(unittest.TestCase):
    def test_takes_max_cumulative_and_counts_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(
                tmp,
                "rollout-x.jsonl",
                meta_line(),
                usage_line(100),
                # 中断ログでは末尾に usage が来ないため、最終行ではなく最大値を採る。
                usage_line(900, rate_limits={"secondary": {"used_percent": 59.0}}),
                json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}),
            )
            parsed = codex_usage.parse_rollout(path)

        self.assertEqual(900, parsed.total)
        self.assertEqual(2, parsed.turns)
        self.assertEqual("Codex Desktop", parsed.originator)
        self.assertEqual("2026-09-01", parsed.date)
        self.assertEqual("user", parsed.thread_source)
        self.assertEqual(59.0, parsed.rate_limits["secondary"]["used_percent"])

    def test_subagent_thread_source_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(tmp, "rollout-sub.jsonl", meta_line(thread_source="subagent"), usage_line(50))
            self.assertEqual("subagent", codex_usage.parse_rollout(path).thread_source)

    def test_log_without_thread_source_falls_back_to_none(self):
        # thread_source は後から入ったフィールドで、古い rollout は持たない（実測で 330 本）。
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(tmp, "rollout-old.jsonl", meta_line(thread_source=""), usage_line(50))
            self.assertEqual("(none)", codex_usage.parse_rollout(path).thread_source)

    def test_last_turn_context_wins_for_model_and_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(
                tmp,
                "rollout-switch.jsonl",
                meta_line(),
                json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.6-luna", "effort": "medium"}}),
                usage_line(10),
                # picker を触ると途中で変わる。代表値は最後に見たもの。
                json.dumps({"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "xhigh"}}),
                usage_line(20),
            )
            parsed = codex_usage.parse_rollout(path)

        self.assertEqual(("gpt-6-astra", "xhigh"), (parsed.model, parsed.effort))

    def test_missing_turn_context_falls_back_to_placeholders(self):
        # turn_context を持たない古いログが実在する（2026-09 時点で 49 セッション）。
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(tmp, "rollout-nocontext.jsonl", meta_line(), usage_line(5))
            parsed = codex_usage.parse_rollout(path)

        self.assertEqual(("(unknown)", "(unset)"), (parsed.model, parsed.effort))

    def test_log_without_start_timestamp_is_skipped(self):
        # 実測では 882 本すべてに timestamp があるので、欠けたログは集計対象から落とす。
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(tmp, "rollout-nots.jsonl", meta_line(timestamp=""), usage_line(77))
            self.assertIsNone(codex_usage.parse_rollout(path))

    def test_log_without_usage_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(tmp, "rollout-empty.jsonl", meta_line())
            self.assertIsNone(codex_usage.parse_rollout(path))

    def test_broken_json_line_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = rollout(tmp, "rollout-broken.jsonl", meta_line(), '{"total_token_usage": broken', usage_line(42))
            self.assertEqual(42, codex_usage.parse_rollout(path).total)


if __name__ == "__main__":
    unittest.main()
