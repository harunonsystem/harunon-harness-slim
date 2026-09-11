#!/usr/bin/env python3
"""Live capability conformance tests.

The tests use parser fixtures and injected subprocess runners; no network or
real model invocation is performed by the default suite.
"""
from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib import live_capabilities


class TestLiveParsers(unittest.TestCase):
    def test_codex_jsonl_parser_normalizes_model_usage_and_tool_name(self):
        output = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "secret"}),
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "tool_call", "name": "cat", "arguments": "secret"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "model": "gpt-5.6-sol",
                        "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
                    }
                ),
            ]
        )

        parsed = live_capabilities.parse_output("codex", output)

        self.assertEqual(parsed.observed_model, "gpt-5.6-sol")
        self.assertEqual(parsed.usage["input_tokens"], 4)
        self.assertEqual(list(parsed.tool_calls), ["cat"])
        self.assertIn("turn.completed", parsed.events)
        self.assertNotIn("secret", json.dumps(parsed.as_dict()))

    def test_claude_stream_parser_reads_assistant_model_and_usage(self):
        output = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-4-5"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-sonnet-4-5",
                            "usage": {"input_tokens": 8, "output_tokens": 2},
                        },
                    }
                ),
                json.dumps({"type": "result", "usage": {"input_tokens": 8, "output_tokens": 2}}),
            ]
        )

        parsed = live_capabilities.parse_output("claude", output)

        self.assertEqual(parsed.observed_model, "claude-sonnet-4-5")
        self.assertEqual(parsed.usage, {"input_tokens": 8, "output_tokens": 2})
        self.assertIn("assistant", parsed.events)

    def test_policy_denial_requires_explicit_denial_text(self):
        denied = live_capabilities.parse_output(
            "opencode", json.dumps({"type": "permission.denied", "message": "secret token"})
        )
        nonzero_like = live_capabilities.parse_output("opencode", "failed with exit 1")

        self.assertTrue(denied.denied)
        self.assertFalse(nonzero_like.denied)

    def test_basic_probe_ignores_prompt_echo_and_unknown_events(self):
        parsed = live_capabilities.parse_codex_output(
            "\n".join(
                (
                    json.dumps({"type": "user", "text": "CAPABILITY_BENCH_BASIC_OK"}),
                    json.dumps({"type": "turn.completed", "text": "not-the-sentinel"}),
                )
            )
        )

        observation = live_capabilities.evaluate_probe(
            "codex", "basic_turn", parsed, exit_code=0
        )

        self.assertFalse(parsed.sentinel)
        self.assertTrue(parsed.terminal_success)
        self.assertEqual(observation.status, "BLOCKED")

    def test_basic_sentinel_uses_each_runtime_terminal_assistant_shape(self):
        fixtures = {
            "claude": [
                {"type": "assistant", "text": "CAPABILITY_BENCH_BASIC_OK"},
                {"type": "result", "result": "CAPABILITY_BENCH_BASIC_OK"},
            ],
            "codex": [
                {"type": "item.completed", "item": {"type": "agent_message", "text": "CAPABILITY_BENCH_BASIC_OK"}},
                {"type": "turn.completed"},
            ],
            "opencode": [
                {"type": "text", "part": {"text": "CAPABILITY_BENCH_BASIC_OK"}},
                {"type": "step-finish"},
            ],
            "pi": [
                {
                    "type": "turn_end",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "checking"},
                            {"type": "text", "text": "CAPABILITY_BENCH_"},
                            {"type": "text", "text": "BASIC_OK"},
                        ],
                    },
                }
            ],
            "omp": [
                {
                    "type": "turn_end",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "checking"},
                            {"type": "text", "text": "CAPABILITY_BENCH_"},
                            {"type": "text", "text": "BASIC_OK"},
                        ],
                    },
                }
            ],
        }
        for target, records in fixtures.items():
            with self.subTest(target=target):
                parsed = live_capabilities.parse_output(target, "\n".join(json.dumps(record) for record in records))
                self.assertTrue(parsed.sentinel)

        echoed = live_capabilities.parse_codex_output(
            json.dumps({"type": "item.completed", "item": {"type": "user_message", "text": "CAPABILITY_BENCH_BASIC_OK"}})
        )
        self.assertFalse(echoed.sentinel)

    def test_basic_sentinel_rejects_error_tool_results_and_later_wrong_terminal_records(self):
        sentinel = "CAPABILITY_BENCH_BASIC_OK"

        claude_error = live_capabilities.parse_output(
            "claude",
            "\n".join(
                (
                    json.dumps({"type": "result", "subtype": "success", "result": sentinel}),
                    json.dumps({"type": "result", "subtype": "error_during_execution", "result": sentinel}),
                )
            ),
        )
        self.assertFalse(claude_error.sentinel)

        claude_tool_result = live_capabilities.parse_output(
            "claude",
            json.dumps(
                {
                    "type": "tool_result",
                    "content": [{"type": "text", "text": sentinel}],
                }
            ),
        )
        self.assertFalse(claude_tool_result.sentinel)

        for nested_result in (
            {"result": sentinel, "error": {"message": "failed"}},
            {"result": sentinel, "toolResults": [{"type": "tool_result"}]},
        ):
            with self.subTest(nested_result=nested_result):
                claude_nested_error = live_capabilities.parse_output(
                    "claude",
                    json.dumps({"type": "result", "result": nested_result}),
                )
                self.assertFalse(claude_nested_error.sentinel)

        codex_wrong = live_capabilities.parse_output(
            "codex",
            "\n".join(
                (
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": sentinel},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": "WRONG"},
                        }
                    ),
                )
            ),
        )
        self.assertFalse(codex_wrong.sentinel)

        for target in ("pi", "omp"):
            with self.subTest(target=target):
                wrong_content = live_capabilities.parse_output(
                    target,
                    "\n".join(
                        (
                            json.dumps(
                                {
                                    "type": "turn_end",
                                    "message": {
                                        "role": "assistant",
                                        "content": [{"type": "text", "text": sentinel}],
                                    },
                                }
                            ),
                            json.dumps(
                                {
                                    "type": "turn_end",
                                    "message": {
                                        "role": "assistant",
                                        "content": [
                                            {"type": "text", "text": sentinel},
                                            {"type": "text", "text": " EXTRA"},
                                        ],
                                    },
                                }
                            ),
                        )
                    ),
                )
                self.assertFalse(wrong_content.sentinel)

    def test_opencode_array_parser_reads_nested_tokens(self):
        output = json.dumps(
            [
                {"type": "step_start"},
                {
                    "type": "step_finish",
                    "model": "openai/gpt-5.6-sol",
                    "tokens": {"input": 11, "output": 5, "total": 16},
                },
            ]
        )

        parsed = live_capabilities.parse_opencode_output(output)

        self.assertEqual(parsed.observed_model, "openai/gpt-5.6-sol")
        self.assertEqual(
            parsed.usage,
            {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16},
        )
        self.assertIn("step_finish", parsed.events)

    def test_native_provider_and_model_fields_are_combined_per_event(self):
        opencode = live_capabilities.parse_opencode_output(
            json.dumps(
                {
                    "type": "step_finish",
                    "providerID": "openai-codex",
                    "modelID": "gpt-5.6-sol",
                    "tokens": {"input": 1, "output": 1},
                }
            )
        )
        pi = live_capabilities.parse_pi_output(
            json.dumps(
                {
                    "type": "message_end",
                    "message": {
                        "provider": "openai-codex",
                        "model": "gpt-5.6-sol",
                    },
                }
            )
        )

        self.assertEqual(opencode.observed_model, "openai-codex/gpt-5.6-sol")
        self.assertEqual(pi.observed_model, "openai-codex/gpt-5.6-sol")

    def test_pi_and_omp_parsers_read_message_usage_aliases(self):
        output = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "model": "openai-codex/gpt-5.6-sol",
                    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
                },
            }
        )

        for parser in (live_capabilities.parse_pi_output, live_capabilities.parse_omp_output):
            with self.subTest(parser=parser.__name__):
                parsed = parser(output)
                self.assertEqual(parsed.observed_model, "openai-codex/gpt-5.6-sol")
                self.assertEqual(
                    parsed.usage,
                    {"input_tokens": 7, "output_tokens": 2},
                )

    def test_tool_name_is_redacted_when_not_allowlisted_or_secret_like(self):
        parsed = live_capabilities.parse_output(
            "opencode",
            json.dumps(
                {
                    "type": "tool_call",
                    "name": "sk-1234567890abcdef",
                    "arguments": "SECRET_VALUE",
                }
            ),
        )

        self.assertEqual(parsed.tool_calls, ("REDACTED",))
        self.assertNotIn("SECRET_VALUE", json.dumps(parsed.as_dict()))
        for formatter in (json.dumps, str):
            self.assertNotIn("1234567890abcdef", formatter(parsed.as_dict()))


class TestDrivers(unittest.TestCase):
    def test_drivers_use_non_bypass_json_invocations_and_stdin(self):
        expected = {
            "claude": ["claude", "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence"],
            "codex": [
                "codex",
                "--ask-for-approval",
                "untrusted",
                "exec",
                "--json",
                "--ephemeral",
                "--cd",
                "/tmp/probe",
                "--sandbox",
                "read-only",
                "-",
            ],
            "opencode": ["opencode", "run", "--format", "json", "--dir", "/tmp/probe"],
            "pi": ["pi", "-p", "--mode", "json", "--no-session"],
            "omp": ["omp", "-p", "--mode", "json", "--no-session", "--cwd", "/tmp/probe"],
        }
        for target, command in expected.items():
            driver = live_capabilities.DRIVERS[target]
            self.assertEqual(driver.command(Path("/tmp/probe")), command)
            self.assertTrue(driver.stdin_prompt)
            self.assertNotIn("yolo", " ".join(command).lower())
            self.assertNotIn("dangerously", " ".join(command).lower())

    def test_expected_models_are_resolved_from_target_ssot(self):
        self.assertEqual(live_capabilities.expected_model(REPO_ROOT, "codex"), "gpt-5.6-luna")
        self.assertEqual(
            live_capabilities.expected_model(REPO_ROOT, "pi"), "openai-codex/gpt-5.6-luna:medium"
        )
        self.assertEqual(
            live_capabilities.expected_model(REPO_ROOT, "omp"), "openai-codex/gpt-5.6-luna:max"
        )
        self.assertIsNone(live_capabilities.expected_model(REPO_ROOT, "opencode"))


class TestVerdicts(unittest.TestCase):
    def test_model_selection_uses_observed_model_and_reports_drift(self):
        parsed = live_capabilities.parse_output(
            "pi", json.dumps({"type": "turn.completed", "model": "openai-codex/gpt-5.6-luna:max"})
        )

        observation = live_capabilities.evaluate_probe(
            "pi",
            "model_selection",
            parsed,
            exit_code=0,
            requested_model="openai-codex/gpt-5.6-sol:medium",
        )

        self.assertEqual(observation.status, "DRIFT")
        self.assertEqual(set(observation.as_dict()), {
            "target", "probe", "status", "requested_model", "observed_model", "observed_thinking", "usage",
            "tool_calls", "exit_code", "events", "reason",
        })

    def test_policy_nonzero_without_denial_is_not_pass(self):
        parsed = live_capabilities.parse_output("codex", "runtime failed")

        observation = live_capabilities.evaluate_probe(
            "codex", "policy_deny", parsed, exit_code=1
        )

        self.assertEqual(observation.status, "BLOCKED")

    def test_run_probe_uses_sanitized_stdout_with_injected_runner(self):
        class Completed:
            returncode = 0
            stdout = "\n".join(
                (
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": "CAPABILITY_BENCH_BASIC_OK"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "thinking_level": "medium",
                            "secret": "do-not-report",
                        }
                    ),
                )
            )

        seen: list[list[str]] = []

        def runner(command, **kwargs):
            seen.append(command)
            self.assertEqual(kwargs["input"], "Reply with exactly CAPABILITY_BENCH_BASIC_OK.")
            return Completed()

        observation = live_capabilities.run_probe(
            REPO_ROOT,
            "codex",
            "basic_turn",
            timeout_seconds=1,
            cwd=Path("/tmp/probe"),
            runner=runner,
        )

        self.assertEqual(observation.status, "PASS")
        self.assertEqual(len(seen), 1)
        self.assertNotIn("do-not-report", json.dumps(observation.as_dict()))

    def test_unsafe_live_target_is_skipped_before_runner_invocation(self):
        calls: list[list[str]] = []

        observation = live_capabilities.run_probe(
            REPO_ROOT,
            "opencode",
            "basic_turn",
            timeout_seconds=1,
            cwd=Path("/tmp/probe"),
            runner=lambda command, **kwargs: calls.append(command),
        )

        self.assertEqual(observation.status, "SKIPPED")
        self.assertEqual(observation.reason, live_capabilities.UNSAFE_LIVE_TARGETS["opencode"])
        self.assertEqual(calls, [])

    def test_blocked_reason_classifies_stderr_without_leaking_it(self):
        class Completed:
            returncode = 1
            stdout = ""
            stderr = "model_catalog missing field supports_reasoning_summaries SECRET_VALUE"

        observation = live_capabilities.run_probe(
            REPO_ROOT,
            "codex",
            "basic_turn",
            timeout_seconds=1,
            cwd=Path("/tmp/probe"),
            runner=lambda command, **kwargs: Completed(),
        )

        self.assertEqual(observation.status, "BLOCKED")
        self.assertEqual(observation.reason, "runtime model catalog is stale")
        self.assertNotIn("SECRET_VALUE", json.dumps(observation.as_dict()))

    def test_timeout_terminates_descendants_and_reaps_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "late-marker"
            executable = root / "slow-runtime"
            executable.write_text(
                "#!/bin/sh\n"
                "(sleep 0.8; : > \"$LIVE_MARKER\") &\n"
                "sleep 10\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            env = os.environ.copy()
            env["LIVE_MARKER"] = str(marker)

            observation = live_capabilities.run_probe(
                REPO_ROOT,
                "pi",
                "basic_turn",
                timeout_seconds=0.1,
                cwd=root,
                driver=live_capabilities.Driver("pi", str(executable)),
                env=env,
            )

            self.assertEqual(observation.status, "BLOCKED")
            time.sleep(1.0)
            self.assertFalse(marker.exists())

    def test_timeout_kills_sigterm_ignoring_grandchild_after_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ready = root / "ready"
            late = root / "late-marker"
            executable = root / "stubborn-runtime"
            # stub は sh で書く。以前は python stub + timeout 0.3s で、フルスイート
            # 実行や pre-push hook の負荷下では interpreter 起動だけで 0.3s を超え、
            # ready 書き込み前に kill されて line 544 の assert が落ちていた
            # （2026-08-05 に push gate を 4 回ブロック）。sh の起動は ~10ms なので
            # timeout 1.0s に対して 2 桁のマージンがある。
            executable.write_text(
                "#!/bin/sh\n"
                "(\n"
                "  trap '' TERM\n"
                '  : > "$LIVE_READY"\n'
                "  sleep 3\n"
                '  : > "$LIVE_LATE"\n'
                ") &\n"
                "sleep 20\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            env = os.environ.copy()
            env["LIVE_READY"] = str(ready)
            env["LIVE_LATE"] = str(late)

            observation = live_capabilities.run_probe(
                REPO_ROOT,
                "pi",
                "basic_turn",
                timeout_seconds=1.0,
                cwd=root,
                driver=live_capabilities.Driver("pi", str(executable)),
                env=env,
            )

            self.assertEqual(observation.status, "BLOCKED")
            self.assertTrue(ready.exists())
            # 生き残った grandchild は起動+3.0s で late を書く。probe 終了(≈1.0s)から
            # 2.5s 待って合計 ≈3.5s 時点で無いことを確認する（kill 漏れの検出は維持）。
            time.sleep(2.5)
            self.assertFalse(late.exists())

    def test_missing_model_expectation_is_skipped(self):
        parsed = live_capabilities.parse_output(
            "opencode", json.dumps({"type": "text", "text": "ok"})
        )
        observation = live_capabilities.evaluate_probe(
            "opencode", "model_selection", parsed, exit_code=0
        )
        self.assertEqual(observation.status, "SKIPPED")


class TestLiveCli(unittest.TestCase):
    def _write_fake_runtimes(self, root: Path, log_path: Path) -> Path:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        usage = {"input_tokens": 3, "output_tokens": 1}
        outputs = {
            "claude": [
                {"type": "assistant", "message": {"model": "claude-sonnet-4-5", "usage": usage}},
                {"type": "result", "result": "CAPABILITY_BENCH_BASIC_OK", "usage": usage},
            ],
            "codex": [
                {"type": "item.completed", "item": {"type": "agent_message", "text": "CAPABILITY_BENCH_BASIC_OK"}},
                {"type": "turn.completed", "model": "gpt-5.6-luna", "thinking_level": "max", "usage": usage},
            ],
            "opencode": [
                {"type": "text", "part": {"text": "CAPABILITY_BENCH_BASIC_OK"}},
                {"type": "step-finish", "providerID": "openai-codex", "modelID": "gpt-5.6-luna", "tokens": usage},
            ],
            "pi": [
                {
                    "type": "turn_end",
                    "message": {
                        "role": "assistant",
                        "provider": "openai-codex",
                        "model": "gpt-5.6-luna",
                        "thinking_level": "medium",
                        "usage": usage,
                        "content": [{"type": "text", "text": "CAPABILITY_BENCH_BASIC_OK"}],
                    },
                }
            ],
            "omp": [
                {
                    "type": "turn_end",
                    "message": {
                        "role": "assistant",
                        "provider": "openai-codex",
                        "model": "gpt-5.6-luna",
                        "thinking_level": "max",
                        "usage": usage,
                        "content": [{"type": "text", "text": "CAPABILITY_BENCH_BASIC_OK"}],
                    },
                }
            ],
        }
        for target, payloads in outputs.items():
            script = bin_dir / target
            output = "".join(
                f"printf '%s\\n' '{json.dumps(payload, separators=(',', ':'))}'\n"
                for payload in payloads
            )
            script.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                'printf \'%s\\n\' "$0 $*" >> "$FAKE_LIVE_LOG"\n'
                'printf \'SECRET_STDERR\\n\' >&2\n'
                + output,
                encoding="utf-8",
            )
            script.chmod(0o755)
        return bin_dir

    def test_fake_executables_cover_all_driver_commands_and_live_report(self):
        cli = SCRIPTS_DIR / "capability-bench.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "invocations.log"
            bin_dir = self._write_fake_runtimes(root, log_path)
            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["FAKE_LIVE_LOG"] = str(log_path)
            result = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--live",
                    "--timeout-seconds",
                    "2",
                    "--format",
                    "json",
                ],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("SECRET_STDERR", result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["mode"], "live")
            self.assertEqual(payload["targets"], ["claude", "codex", "omp", "opencode", "pi"])
            self.assertEqual(len(payload["observations"]), 30)
            statuses = {observation["status"] for observation in payload["observations"]}
            self.assertTrue(statuses <= {"PASS", "SKIPPED"})
            self.assertEqual(
                {observation["probe"] for observation in payload["observations"]},
                set(live_capabilities.PROBE_NAMES),
            )
            log = log_path.read_text(encoding="utf-8")
            log_lines = log.splitlines()
            for target in ("claude", "codex", "opencode", "pi", "omp"):
                self.assertEqual(
                    sum(line.endswith(f"/bin/{target}") or f"/bin/{target} " in line for line in log_lines),
                    0 if target == "opencode" else 1,
                    target,
                )
            self.assertIn("claude -p --output-format stream-json --verbose --no-session-persistence", log)
            self.assertIn("codex --ask-for-approval untrusted exec --json --ephemeral --cd", log)
            self.assertIn("--ask-for-approval untrusted exec --json", log)
            self.assertIn("--sandbox read-only -", log)
            self.assertNotIn("opencode run --format json --dir", log)
            self.assertIn("pi -p --mode json --no-session", log)
            self.assertIn("omp -p --mode json --no-session --cwd", log)

    def test_live_model_drift_exits_one_without_stderr_or_raw_output(self):
        cli = SCRIPTS_DIR / "capability-bench.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "invocations.log"
            bin_dir = self._write_fake_runtimes(root, log_path)
            codex = bin_dir / "codex"
            # 期待モデル（_write_fake_runtimes が返す値）を別モデルに差し替えて drift を作る。
            # 置換元は SSOT の codex default と一致していないと drift が起きずテストが空振りする。
            codex.write_text(
                codex.read_text(encoding="utf-8").replace("gpt-5.6-luna", "gpt-5.6-sol"),
                encoding="utf-8",
            )
            codex.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["FAKE_LIVE_LOG"] = str(log_path)
            result = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--live",
                    "--targets",
                    "codex",
                    "--timeout-seconds",
                    "2",
                    "--format",
                    "markdown",
                ],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("DRIFT", result.stdout)
            self.assertNotIn("SECRET_STDERR", result.stdout)
            self.assertNotIn("Traceback", result.stderr)

    def test_all_observation_fields_are_sanitized_in_three_formats(self):
        secret = "sk-1234567890abcdef"
        observation = live_capabilities.Observation(
            target="codex",
            probe="basic_turn",
            status="BLOCKED",
            requested_model=secret,
            observed_model=secret,
            observed_thinking=secret,
            usage={"secret_key": 1, "input_tokens": 2},
            tool_calls=(secret, "bad\nname"),
            exit_code=1,
            events=(secret, "turn.completed"),
            reason=secret,
        )
        report = {
            "schemaVersion": 1,
            "mode": "live",
            "targets": ["codex"],
            "dimensions": list("dimension"),
            "probes": list(live_capabilities.PROBE_NAMES),
            "observations": [observation.as_dict()],
            "findings": [],
        }
        spec = importlib.util.spec_from_file_location("capability_bench", SCRIPTS_DIR / "capability-bench.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for rendered in (module._json(report), module._markdown(report), module._terminal(report)):
            self.assertNotIn(secret, rendered)
            self.assertNotIn("secret_key", rendered)
            self.assertNotIn("bad\nname", rendered)


if __name__ == "__main__":
    unittest.main()
