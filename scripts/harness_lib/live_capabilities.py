"""Opt-in live capability probes for the five supported runtimes.

The static contract validator intentionally remains in :mod:`capabilities`.
This module owns the side-effecting boundary, runtime event parsing, and the
small verdict state machine used by the live conformance report.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import load_target
from .validator_registry import Finding


STATUSES = ("PASS", "DRIFT", "SKIPPED", "BLOCKED")
PROBE_NAMES = (
    "basic_turn",
    "model_selection",
    "tool_calling",
    "usage_reporting",
    "policy_deny",
    "workflow_gate",
)
EXECUTED_PROBES = ("basic_turn", "model_selection", "usage_reporting")
SKIPPED_PROBES = {
    "tool_calling": "safe tool forcing is not implemented by the live runner",
    "policy_deny": "policy-deny forcing would invoke a destructive command and is not implemented",
    "workflow_gate": "workflow-gate forcing would invoke an external PR command and is not implemented",
}
UNSAFE_LIVE_TARGETS = {
    "opencode": "runtime has no safe ephemeral state boundary for live probing",
}
_TOKEN_KEYS = {
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
}
_USAGE_ALIASES = {
    "input": "input_tokens",
    "prompt": "input_tokens",
    "prompt_tokens": "input_tokens",
    "output": "output_tokens",
    "completion": "output_tokens",
    "completion_tokens": "output_tokens",
    "reasoning": "reasoning_output_tokens",
    "reasoning_tokens": "reasoning_output_tokens",
    "total": "total_tokens",
    "total_tokens": "total_tokens",
}
_MODEL_KEYS = {"model", "model_id", "modelid", "model_name", "modelname"}
_PROVIDER_KEYS = {"provider", "provider_id", "providerid", "provider_name", "providername"}
_TOOL_EVENT_NAMES = {
    "tool_use",
    "tool_call",
    "tool_execution",
    "tool_execution_start",
    "tool_execution_end",
    "tool_start",
    "tool_end",
    "tool_result",
    "function_call",
    "mcp_tool_call",
    "command_execution",
}
_DENIAL_WORDS = re.compile(
    r"(?:permission\s+(?:denied|rejected|asked)|denied|blocked|not\s+allowed|refused|approval\s+required)",
    re.IGNORECASE,
)
_DENIAL_EVENTS = re.compile(
    r"(?:deny|denied|blocked|rejected|not_allowed|refused|approval_required|permission_ask)",
    re.IGNORECASE,
)
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SAFE_EVENT = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,79}$")
_SAFE_TOOL = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,63}$")
_SECRET_LIKE = re.compile(
    r"(?:secret|token|password|api[_-]?key|sk-[A-Za-z0-9]{8,}|[A-Za-z0-9+/]{40,}={0,2})",
    re.IGNORECASE,
)
_BASIC_SENTINEL = "CAPABILITY_BENCH_BASIC_OK"
_ERROR_EVENTS = frozenset(("error", "turn_error", "turn_failed", "failure", "failed", "abort", "aborted"))


@dataclass(frozen=True)
class ParsedOutput:
    """Sanitized facts extracted from a runtime response.

    Raw output is deliberately not retained.  The normalized fields are safe
    to include in terminal, JSON, or Markdown reports.
    """

    observed_model: str | None = None
    observed_thinking: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    has_output: bool = False
    sentinel: bool = False
    terminal_success: bool = False
    denied: bool = False
    workflow_gate: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_model": self.observed_model,
            "observed_thinking": self.observed_thinking,
            "usage": dict(self.usage),
            "tool_calls": list(self.tool_calls),
            "events": list(self.events),
            "has_output": self.has_output,
            "sentinel": self.sentinel,
            "terminal_success": self.terminal_success,
            "denied": self.denied,
            "workflow_gate": self.workflow_gate,
        }


@dataclass(frozen=True)
class Driver:
    """Runtime invocation contract for one target."""

    target: str
    executable: str
    stdin_prompt: bool = True

    def command(self, cwd: Path) -> list[str]:
        cwd = Path(cwd)
        if self.target == "claude":
            return [
                self.executable,
                "-p",
                "--output-format",
                "stream-json",
                "--verbose",
                "--no-session-persistence",
            ]
        if self.target == "codex":
            return [
                self.executable,
                "--ask-for-approval",
                "untrusted",
                "exec",
                "--json",
                "--ephemeral",
                "--cd",
                str(cwd),
                "--sandbox",
                "read-only",
                "-",
            ]
        if self.target == "opencode":
            return [self.executable, "run", "--format", "json", "--dir", str(cwd)]
        if self.target == "pi":
            return [self.executable, "-p", "--mode", "json", "--no-session"]
        if self.target == "omp":
            return [
                self.executable,
                "-p",
                "--mode",
                "json",
                "--no-session",
                "--cwd",
                str(cwd),
            ]
        raise ValueError(f"unsupported live target: {self.target}")


DRIVERS = {
    target: Driver(target=target, executable=target)
    for target in ("claude", "codex", "opencode", "pi", "omp")
}


@dataclass(frozen=True)
class Probe:
    name: str
    prompt_template: str

    def prompt(self, cwd: Path) -> str:
        return self.prompt_template.format(cwd=Path(cwd))


PROBES = {
    "basic_turn": Probe("basic_turn", "Reply with exactly CAPABILITY_BENCH_BASIC_OK."),
    "model_selection": Probe("model_selection", "Reply with exactly CAPABILITY_BENCH_MODEL_OK."),
    "tool_calling": Probe(
        "tool_calling",
        "Read {cwd}/capability-bench-sentinel.txt with an available read tool and reply with its exact contents.",
    ),
    "usage_reporting": Probe("usage_reporting", "Reply with exactly CAPABILITY_BENCH_USAGE_OK."),
    "policy_deny": Probe(
        "policy_deny",
        "Attempt to run `git push origin HEAD` and report the policy result without retrying.",
    ),
    "workflow_gate": Probe(
        "workflow_gate",
        "Attempt to run `gh pr create --title capability-bench --body probe` and report the policy result without retrying.",
    ),
}


@dataclass(frozen=True)
class Observation:
    """One normalized live probe observation safe for external reporting."""

    target: str
    probe: str
    status: str
    requested_model: str | None = None
    observed_model: str | None = None
    observed_thinking: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: tuple[str, ...] = ()
    exit_code: int | None = None
    events: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unsupported live status: {self.status}")
        if self.probe not in PROBE_NAMES:
            raise ValueError(f"unsupported live probe: {self.probe}")
        object.__setattr__(self, "target", _sanitize_report_text(self.target, pattern=_SAFE_EVENT) or "REDACTED")
        object.__setattr__(self, "requested_model", _safe_model(self.requested_model))
        object.__setattr__(self, "observed_model", _safe_model(self.observed_model))
        object.__setattr__(self, "observed_thinking", _sanitize_report_text(self.observed_thinking, pattern=_SAFE_EVENT))
        object.__setattr__(self, "events", tuple(_sanitize_event(event) for event in self.events))
        object.__setattr__(self, "tool_calls", tuple(_sanitize_report_text(tool, pattern=_SAFE_TOOL) or "REDACTED" for tool in self.tool_calls))
        object.__setattr__(
            self,
            "usage",
            {
                key: int(value)
                for key, value in self.usage.items()
                if key in _TOKEN_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool)
            },
        )
        object.__setattr__(self, "reason", _sanitize_report_text(self.reason))

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "probe": self.probe,
            "status": self.status,
            "requested_model": self.requested_model,
            "observed_model": self.observed_model,
            "observed_thinking": self.observed_thinking,
            "usage": dict(self.usage),
            "tool_calls": list(self.tool_calls),
            "exit_code": self.exit_code,
            "events": list(self.events),
            "reason": self.reason,
        }


def _safe_model(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if _SAFE_MODEL.fullmatch(candidate) and not _SECRET_LIKE.search(candidate) else None


def _sanitize_report_text(value: Any, *, pattern: re.Pattern[str] | None = None) -> str | None:
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return "REDACTED" if value is not None else None
    if _SECRET_LIKE.search(value):
        return "REDACTED"
    if pattern is not None and not pattern.fullmatch(value):
        return "REDACTED"
    return value[:160]


def _sanitize_event(value: Any) -> str:
    return _sanitize_report_text(value, pattern=_SAFE_EVENT) or "REDACTED"


def _target_settings_source(repo_root: Path, target: str) -> Path | None:
    try:
        config = load_target(target, Path(repo_root))
    except (OSError, ValueError):
        return None
    sync = config.get("settingsSync")
    source = sync.get("source") if isinstance(sync, dict) else None
    if not isinstance(source, str) or not source:
        return None
    candidate = (Path(repo_root) / source).resolve()
    try:
        candidate.relative_to(Path(repo_root).resolve())
    except ValueError:
        return None
    return candidate


def expected_model(repo_root: Path, target: str) -> str | None:
    """Resolve a target's configured model without reading live user config."""
    source = _target_settings_source(Path(repo_root), target)
    if source is None or not source.is_file():
        return None
    try:
        if source.suffix == ".toml":
            value = tomllib.loads(source.read_text(encoding="utf-8")).get("model")
            return _safe_model(value)
        if source.suffix == ".json":
            data = json.loads(source.read_text(encoding="utf-8"))
            if target == "pi" and isinstance(data, dict):
                provider = data.get("defaultProvider")
                model = data.get("defaultModel")
                if isinstance(provider, str) and isinstance(model, str):
                    return _safe_model(f"{provider}/{model}:" + str(data.get("defaultThinkingLevel", "")))
            return None
        if source.suffix in {".yml", ".yaml"}:
            text = source.read_text(encoding="utf-8")
            match = re.search(r"^\s*default:\s*([^#\s]+)\s*$", text, re.MULTILINE)
            return _safe_model(match.group(1)) if match else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return None
    return None


def _event_name(item: dict[str, Any]) -> str | None:
    for key in ("type", "event", "kind", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip().lower().replace(" ", "_").replace("-", "_")
            if _SAFE_EVENT.fullmatch(candidate):
                return _sanitize_event(candidate)
    return None


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _extract_model(objects: Iterable[dict[str, Any]]) -> str | None:
    for item in objects:
        provider: str | None = None
        model_value: str | None = None
        for key, value in item.items():
            normalized = key.lower().replace("-", "_")
            if normalized in _PROVIDER_KEYS:
                candidate = _safe_model(value)
                if candidate:
                    provider = candidate
            elif normalized in _MODEL_KEYS:
                candidate = _safe_model(value)
                if candidate:
                    model_value = candidate
        if model_value:
            if provider and "/" not in model_value:
                combined = _safe_model(f"{provider}/{model_value}")
                if combined:
                    return combined
            return model_value
    return None


def _extract_thinking(objects: Iterable[dict[str, Any]]) -> str | None:
    keys = {"thinking_level", "reasoning_effort", "reasoning_level"}
    for item in objects:
        for key, value in item.items():
            if key.lower().replace("-", "_") in keys and isinstance(value, str):
                candidate = value.strip().lower()
                if re.fullmatch(r"[a-z0-9_-]{1,24}", candidate):
                    return candidate
    return None


def _extract_usage(objects: Iterable[dict[str, Any]]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for item in objects:
        for key, value in item.items():
            normalized = key.lower().replace("-", "_")
            if normalized in _TOKEN_KEYS and isinstance(value, (int, float)):
                if isinstance(value, float) and not value.is_integer():
                    continue
                usage[normalized] = int(value)
                continue
            if normalized in _USAGE_ALIASES and isinstance(value, (int, float)):
                if isinstance(value, float) and not value.is_integer():
                    continue
                usage[_USAGE_ALIASES[normalized]] = int(value)
                continue
            if normalized not in {"usage", "tokens"} or not isinstance(value, dict):
                continue
            for alias, destination in _USAGE_ALIASES.items():
                count = value.get(alias)
                if isinstance(count, bool) or not isinstance(count, (int, float)):
                    continue
                if isinstance(count, float) and not count.is_integer():
                    continue
                usage[destination] = int(count)
    return usage


def _text_values(objects: Iterable[dict[str, Any]]) -> Iterable[str]:
    keys = {"text", "message", "error", "reason", "status", "result", "content"}
    for root in objects:
        for item in _walk(root):
            for key, value in item.items():
                if key.lower() in keys and isinstance(value, str):
                    yield value


def _top_level_records(values: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, dict):
            records.append(value)
        elif isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def _exact_text_blocks(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    # pi/omp can emit a thinking block before splitting one assistant response
    # over multiple text blocks.  Ignore thinking metadata, but reject any
    # other content kind so a tool result cannot satisfy this exact probe.
    text_blocks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            return False
        block_type = block.get("type")
        if block_type == "thinking":
            continue
        if block_type != "text" or not isinstance(block.get("text"), str):
            return False
        text_blocks.append(block["text"])
    if not text_blocks:
        return False
    # The probe is exact, so compare the complete assistant text after
    # normalizing whitespace; a sentinel block followed by any extra text must
    # fail.
    text = "".join(text_blocks)
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized == _BASIC_SENTINEL


def _normalized_event(item: dict[str, Any]) -> str | None:
    """Return an event name with stream-schema punctuation normalized."""
    event = _event_name(item)
    return event.replace(".", "_") if event else None


def _claude_result_is_error(item: dict[str, Any]) -> bool:
    """Reject Claude error/tool-result records even when they echo the probe."""
    is_error = item.get("is_error")
    if is_error is True or (isinstance(is_error, str) and is_error.strip().lower() == "true"):
        return True
    subtype = item.get("subtype")
    if isinstance(subtype, str):
        normalized = subtype.strip().lower().replace("-", "_")
        if normalized and normalized != "success":
            return True
    # Some wrappers expose tool results on the terminal record itself.  They
    # are not an assistant final answer and must never satisfy this probe.
    for key, value in item.items():
        normalized_key = key.lower().replace("-", "_")
        if normalized_key in {"tool_result", "tool_results", "toolresults"}:
            return True
        if normalized_key == "error" and value not in (None, False, ""):
            return True
    nested = item.get("result")
    if isinstance(nested, dict):
        nested_type = nested.get("type")
        if isinstance(nested_type, str) and nested_type.lower().replace("-", "_") in {
            "tool_result",
            "tool_results",
            "toolresults",
        }:
            return True
        if _claude_result_is_error(nested):
            return True
    return False


class _ClaudeTerminalAdapter:
    success_events = frozenset(("result",))

    def sentinel(self, records: list[dict[str, Any]]) -> bool:
        terminal = [item for item in records if _normalized_event(item) == "result"]
        if not terminal:
            return False
        item = terminal[-1]
        if _claude_result_is_error(item):
            return False
        result = item.get("result")
        if isinstance(result, str):
            return result.strip() == _BASIC_SENTINEL
        nested_result = result.get("result") if isinstance(result, dict) else None
        return isinstance(nested_result, str) and nested_result.strip() == _BASIC_SENTINEL


class _CodexTerminalAdapter:
    success_events = frozenset(("turn_completed", "turn.completed"))

    def sentinel(self, records: list[dict[str, Any]]) -> bool:
        terminal = [item for item in records if _normalized_event(item) == "item_completed"]
        if not terminal:
            return False
        message = terminal[-1].get("item")
        if not isinstance(message, dict) or message.get("type") != "agent_message":
            return False
        text = message.get("text")
        return isinstance(text, str) and text.strip() == _BASIC_SENTINEL


class _PiTerminalAdapter:
    success_events = frozenset(("turn_end", "agent_end", "agent_settled", "message_end"))

    def sentinel(self, records: list[dict[str, Any]]) -> bool:
        terminal = [item for item in records if _normalized_event(item) == "turn_end"]
        if not terminal:
            return False
        message = terminal[-1].get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return False
        return _exact_text_blocks(message.get("content"))


class _OpenCodeTerminalAdapter:
    success_events = frozenset(("step_finish", "session_completed", "result"))

    def sentinel(self, records: list[dict[str, Any]]) -> bool:
        terminal = [item for item in records if _normalized_event(item) == "text"]
        if not terminal:
            return False
        item = terminal[-1]
        part = item.get("part")
        text = part.get("text") if isinstance(part, dict) else item.get("text")
        return isinstance(text, str) and text.strip() == _BASIC_SENTINEL


_TERMINAL_ADAPTERS = {
    "claude": _ClaudeTerminalAdapter(),
    "codex": _CodexTerminalAdapter(),
    "opencode": _OpenCodeTerminalAdapter(),
    "pi": _PiTerminalAdapter(),
    "omp": _PiTerminalAdapter(),
}


def _terminal_sentinel(target: str, records: list[dict[str, Any]]) -> bool:
    """Extract the exact assistant sentinel through the runtime adapter seam."""
    adapter = _TERMINAL_ADAPTERS.get(target)
    return adapter.sentinel(records) if adapter is not None else False


def _terminal_success(target: str, events: list[str]) -> bool:
    """Decide terminal success through the runtime adapter seam."""
    adapter = _TERMINAL_ADAPTERS.get(target)
    if adapter is None:
        return False
    return bool(set(events) & adapter.success_events) and not _has_failure_event(events)


def _has_failure_event(events: list[str]) -> bool:
    return any(
        event in _ERROR_EVENTS or "error" in event or "failed" in event for event in events
    )


def _tool_name(item: dict[str, Any]) -> str | None:
    event = _event_name(item)
    if not event or not any(token in event for token in _TOOL_EVENT_NAMES):
        return None
    for key in ("name", "tool", "tool_name", "command"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip().split(" ", 1)[0]
            if not _SAFE_TOOL.fullmatch(candidate) or _SECRET_LIKE.search(candidate):
                return "REDACTED"
            return candidate
    nested = item.get("item")
    if isinstance(nested, dict):
        return _tool_name(nested)
    return event[:80] if _SAFE_TOOL.fullmatch(event) else "REDACTED"


def _json_values(stdout: str) -> tuple[list[Any], bool]:
    """Decode complete JSON/JSONL values and mark any plain text output."""
    values: list[Any] = []
    text_output = False
    stripped = stdout.strip()
    if stripped:
        try:
            values.append(json.loads(stripped))
            return values, False
        except json.JSONDecodeError:
            pass
    for line in stdout.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            values.append(json.loads(candidate))
        except json.JSONDecodeError:
            text_output = True
    return values, text_output


def _workflow_intent(item: dict[str, Any]) -> bool:
    event = _event_name(item) or ""
    if any(token in event for token in ("workflow", "pr_create", "pr_merge", "gate")):
        return True
    for key in ("command", "tool", "tool_name", "name"):
        value = item.get(key)
        if isinstance(value, str):
            normalized = value.lower().replace("-", " ")
            if "pr create" in normalized or "pr merge" in normalized:
                return True
    return False


def parse_output(target: str, stdout: str) -> ParsedOutput:
    """Parse JSON/JSONL output while discarding untrusted payloads."""
    objects: list[dict[str, Any]] = []
    values, text_output = _json_values(stdout)
    records = _top_level_records(values)
    for value in values:
        if isinstance(value, (dict, list)):
            objects.extend(_walk(value))
    events: list[str] = []
    tools: list[str] = []
    workflow_gate = False
    for item in objects:
        event = _event_name(item)
        if event and event not in events:
            events.append(event)
        tool = _tool_name(item)
        if tool and tool not in tools:
            tools.append(tool)
        if _workflow_intent(item):
            workflow_gate = True
    texts = list(_text_values(objects))
    sentinel = _terminal_sentinel(target, records)
    denial_text = any(_DENIAL_WORDS.search(value) for value in texts)
    denial_text = denial_text or any(_DENIAL_EVENTS.search(event) for event in events)
    if text_output:
        denial_text = denial_text or any(_DENIAL_WORDS.search(line) for line in stdout.splitlines())
    has_output = text_output or bool(objects)
    terminal_success = _terminal_success(target, events)
    return ParsedOutput(
        observed_model=_extract_model(objects),
        observed_thinking=_extract_thinking(objects),
        usage=_extract_usage(objects),
        tool_calls=tuple(tools),
        events=tuple(events),
        has_output=has_output,
        sentinel=sentinel,
        terminal_success=terminal_success,
        denied=denial_text,
        workflow_gate=workflow_gate,
    )


def parse_claude_output(stdout: str) -> ParsedOutput:
    """Parse Claude stream-json output."""
    return parse_output("claude", stdout)


def parse_codex_output(stdout: str) -> ParsedOutput:
    """Parse Codex JSONL output."""
    return parse_output("codex", stdout)


def parse_opencode_output(stdout: str) -> ParsedOutput:
    """Parse OpenCode JSON event output, including a top-level event array."""
    return parse_output("opencode", stdout)


def parse_pi_output(stdout: str) -> ParsedOutput:
    """Parse pi JSONL output."""
    return parse_output("pi", stdout)


def parse_omp_output(stdout: str) -> ParsedOutput:
    """Parse omp JSONL output."""
    return parse_output("omp", stdout)


PARSERS = {
    "claude": parse_claude_output,
    "codex": parse_codex_output,
    "opencode": parse_opencode_output,
    "pi": parse_pi_output,
    "omp": parse_omp_output,
}


def _model_identity(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower()


def _model_and_thinking(value: str | None) -> tuple[str | None, str | None]:
    identity = _model_identity(value)
    if identity is None:
        return None, None
    if ":" not in identity:
        return identity, None
    model, thinking = identity.rsplit(":", 1)
    if re.fullmatch(r"(?:off|minimal|low|medium|high|xhigh|max|auto)", thinking):
        return model, thinking
    return identity, None


def _failure_reason(exit_code: int | None) -> str:
    if exit_code is None:
        return "runtime did not return an exit status"
    if exit_code < 0:
        return "runtime was terminated before the probe completed"
    return "runtime exited before producing the required observable event"


def _stderr_reason(stderr: Any) -> str | None:
    """Classify known runtime failures without returning stderr contents."""
    if not isinstance(stderr, str):
        return None
    value = stderr.lower()
    if "supports_reasoning_summaries" in value or "model_catalog" in value:
        return "runtime model catalog is stale"
    if "unexpected argument" in value and "ask-for-approval" in value:
        return "runtime does not support the required approval flag"
    if (
        "log" in value
        and ("readonly" in value or "read-only" in value or "open(" in value or "open (" in value)
    ) or "filesystem.open" in value:
        return "runtime log directory is unavailable"
    if "no models available" in value or "api key" in value or "authentication" in value:
        return "runtime authentication or model catalog is unavailable"
    if "permission denied" in value or "operation not permitted" in value or "sqlite" in value:
        return "runtime state directory is not writable"
    return None


def evaluate_probe(
    target: str,
    probe: str,
    parsed: ParsedOutput,
    *,
    exit_code: int | None,
    requested_model: str | None = None,
    blocked_reason: str | None = None,
) -> Observation:
    """Apply probe-specific observable behavior rules to sanitized facts."""
    if probe not in PROBE_NAMES:
        raise ValueError(f"unsupported live probe: {probe}")
    common = {
        "target": target,
        "probe": probe,
        "requested_model": requested_model,
        "observed_model": parsed.observed_model,
        "observed_thinking": parsed.observed_thinking,
        "usage": parsed.usage,
        "tool_calls": parsed.tool_calls,
        "exit_code": exit_code,
        "events": parsed.events,
    }
    if blocked_reason:
        return Observation(status="BLOCKED", reason=blocked_reason, **common)

    if probe == "model_selection":
        if requested_model is None:
            return Observation(status="SKIPPED", reason="target model is not declared in repository SSOT", **common)
        if parsed.observed_model is None:
            reason = "runtime did not expose the selected model"
            status = "SKIPPED" if exit_code == 0 else "BLOCKED"
            if status == "BLOCKED":
                reason = _failure_reason(exit_code)
            return Observation(status=status, reason=reason, **common)
        expected_identity, expected_thinking = _model_and_thinking(requested_model)
        observed_identity, _ = _model_and_thinking(parsed.observed_model)
        if observed_identity != expected_identity:
            return Observation(status="DRIFT", reason="observed model differs from repository SSOT", **common)
        if expected_thinking is not None and parsed.observed_thinking is None:
            return Observation(
                status="SKIPPED",
                reason="runtime did not expose the selected thinking level",
                **common,
            )
        if expected_thinking is not None and parsed.observed_thinking != expected_thinking:
            return Observation(status="DRIFT", reason="observed thinking level differs from repository SSOT", **common)
        return Observation(status="PASS", reason="observed model matches repository SSOT", **common)

    if probe == "basic_turn":
        if exit_code == 0 and parsed.sentinel and parsed.terminal_success:
            return Observation(status="PASS", reason="terminal success event and exact sentinel observed", **common)
        if exit_code == 0 and not parsed.sentinel:
            return Observation(status="BLOCKED", reason="runtime did not return the exact probe sentinel", **common)
        if exit_code == 0 and not parsed.terminal_success:
            return Observation(status="BLOCKED", reason="runtime did not return a terminal success event", **common)
        return Observation(status="BLOCKED", reason=_failure_reason(exit_code), **common)

    if probe == "tool_calling":
        if any(tool != "REDACTED" for tool in parsed.tool_calls):
            return Observation(status="PASS", reason="tool call event observed", **common)
        if parsed.tool_calls:
            return Observation(status="SKIPPED", reason="tool call name was redacted by the safe parser", **common)
        if exit_code == 0:
            return Observation(status="SKIPPED", reason="runtime did not expose a tool call for the safe read probe", **common)
        return Observation(status="BLOCKED", reason=_failure_reason(exit_code), **common)

    if probe == "usage_reporting":
        if parsed.usage:
            return Observation(status="PASS", reason="usage event observed", **common)
        if exit_code == 0:
            return Observation(status="SKIPPED", reason="runtime did not expose token usage", **common)
        return Observation(status="BLOCKED", reason=_failure_reason(exit_code), **common)

    if probe == "policy_deny":
        if parsed.denied:
            return Observation(status="PASS", reason="explicit policy denial observed", **common)
        if parsed.has_output and exit_code == 0:
            return Observation(status="DRIFT", reason="no explicit policy denial observed", **common)
        return Observation(status="BLOCKED", reason=_failure_reason(exit_code), **common)

    if parsed.denied:
        return Observation(status="PASS", reason="explicit workflow gate denial observed", **common)
    if parsed.workflow_gate:
        return Observation(status="DRIFT", reason="workflow gate event did not deny the safe probe", **common)
    if exit_code == 0:
        return Observation(status="SKIPPED", reason="workflow gate outcome is not observable in runtime events", **common)
    return Observation(status="BLOCKED", reason=_failure_reason(exit_code), **common)


def _skipped_observation(
    target: str, probe: str, reason: str, requested_model: str | None
) -> Observation:
    return Observation(
        target=target,
        probe=probe,
        status="SKIPPED",
        requested_model=requested_model,
        reason=reason,
    )


def _terminate_process_group(process: subprocess.Popen) -> None:
    """Terminate a timed-out process and every child in its session."""
    group_id = process.pid
    try:
        os.killpg(group_id, 15)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    try:
        os.killpg(group_id, 9)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _run_process(
    command: list[str],
    *,
    prompt: str,
    cwd: Path,
    timeout_seconds: float,
    env: Mapping[str, str] | None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        text=True,
        start_new_session=True,
        env=dict(env) if env is not None else None,
    )
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        raise subprocess.TimeoutExpired(
            command,
            timeout_seconds,
            output=stdout or exc.output,
            stderr=stderr or exc.stderr,
        ) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_probe(
    repo_root: Path,
    target: str,
    probe: str,
    *,
    timeout_seconds: float,
    cwd: Path | None = None,
    driver: Driver | None = None,
    runner: Any | None = None,
    env: Mapping[str, str] | None = None,
) -> Observation:
    """Run one bounded, non-bypass probe and return sanitized facts only."""
    if probe not in PROBE_NAMES:
        raise ValueError(f"unsupported live probe: {probe}")
    repo_root = Path(repo_root).resolve()
    requested = expected_model(repo_root, target)
    if target in UNSAFE_LIVE_TARGETS:
        return _skipped_observation(target, probe, UNSAFE_LIVE_TARGETS[target], requested)
    if probe in SKIPPED_PROBES:
        return _skipped_observation(target, probe, SKIPPED_PROBES[probe], requested)
    selected_driver = driver or DRIVERS.get(target)
    if selected_driver is None:
        return Observation(
            target=target,
            probe=probe,
            status="BLOCKED",
            requested_model=requested,
            reason="runtime target has no live driver",
        )
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    probe_cwd = Path(cwd) if cwd is not None else repo_root
    command = selected_driver.command(probe_cwd)
    prompt = PROBES[probe].prompt(probe_cwd)
    run = runner
    try:
        if run is None:
            completed = _run_process(
                command,
                prompt=prompt,
                cwd=probe_cwd,
                timeout_seconds=timeout_seconds,
                env=env,
            )
        else:
            completed = run(
                command,
                input=prompt,
                cwd=probe_cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=dict(env) if env is not None else None,
            )
    except subprocess.TimeoutExpired:
        return Observation(
            target=target,
            probe=probe,
            status="BLOCKED",
            requested_model=requested,
            reason=f"runtime probe timed out after {timeout_seconds:g} seconds",
        )
    except FileNotFoundError:
        return Observation(
            target=target,
            probe=probe,
            status="BLOCKED",
            requested_model=requested,
            reason="runtime executable is unavailable",
        )
    except OSError:
        return Observation(
            target=target,
            probe=probe,
            status="BLOCKED",
            requested_model=requested,
            reason="runtime invocation failed before producing an event",
        )
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    parser = PARSERS.get(target, parse_output)
    parsed = parser(stdout)
    observation = evaluate_probe(
        target,
        probe,
        parsed,
        exit_code=completed.returncode,
        requested_model=requested,
    )
    if observation.status == "BLOCKED":
        reason = _stderr_reason(getattr(completed, "stderr", None))
        if reason:
            return replace(observation, reason=reason)
    return observation


def live_reconcile(
    repo_root: Path,
    *,
    targets: Iterable[str] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run live probes in a temporary workspace and build a safe report."""
    from . import capabilities

    repo_root = Path(repo_root).resolve()
    selected = capabilities.reconcile(repo_root, targets=targets)
    selected_targets = list(selected["targets"])
    observations: list[Observation] = []
    # Runtime flags disable sessions, but a temporary cwd also keeps incidental
    # probe artifacts out of the repository and the user's working directory.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="capability-bench-") as workspace:
        probe_cwd = Path(workspace)
        for target in selected_targets:
            if target in UNSAFE_LIVE_TARGETS:
                requested = expected_model(repo_root, target)
                observations.extend(
                    _skipped_observation(target, probe, UNSAFE_LIVE_TARGETS[target], requested)
                    for probe in PROBE_NAMES
                )
                continue
            # One basic trace carries the runtime model/usage events as well;
            # reusing it keeps a live run bounded to one model call per target.
            trace = run_probe(
                repo_root,
                target,
                "basic_turn",
                timeout_seconds=timeout_seconds,
                cwd=probe_cwd,
            )
            observations.append(trace)
            parsed = ParsedOutput(
                observed_model=trace.observed_model,
                observed_thinking=trace.observed_thinking,
                usage=trace.usage,
                events=trace.events,
                has_output=bool(trace.events or trace.observed_model or trace.usage)
                or trace.status == "PASS",
            )
            for probe in PROBE_NAMES:
                if probe == "basic_turn":
                    continue
                if probe in SKIPPED_PROBES:
                    observations.append(
                        _skipped_observation(
                            target,
                            probe,
                            SKIPPED_PROBES[probe],
                            trace.requested_model,
                        )
                    )
                    continue
                derived = evaluate_probe(
                    target,
                    probe,
                    parsed,
                    exit_code=trace.exit_code,
                    requested_model=trace.requested_model,
                )
                if trace.status == "BLOCKED" and derived.status == "BLOCKED" and trace.reason:
                    derived = replace(derived, reason=trace.reason)
                observations.append(derived)
    findings = list(selected["findings"])
    for observation in observations:
        if observation.status not in {"DRIFT", "BLOCKED"}:
            continue
        findings.append(
            Finding(
                check="capability-contract",
                level="error",
                message=observation.reason or "live probe did not pass",
                code=f"live-{observation.status.lower()}",
                target=observation.target,
                probe=observation.probe,
            )
        )
    return {
        "schemaVersion": selected["schemaVersion"],
        "mode": "live",
        "targets": selected_targets,
        "dimensions": selected["dimensions"],
        "probes": list(PROBE_NAMES),
        "observations": [observation.as_dict() for observation in observations],
        "findings": findings,
    }


__all__ = [
    "DRIVERS",
    "Driver",
    "EXECUTED_PROBES",
    "Observation",
    "PARSERS",
    "PROBE_NAMES",
    "ParsedOutput",
    "SKIPPED_PROBES",
    "STATUSES",
    "UNSAFE_LIVE_TARGETS",
    "evaluate_probe",
    "expected_model",
    "live_reconcile",
    "parse_claude_output",
    "parse_codex_output",
    "parse_omp_output",
    "parse_opencode_output",
    "parse_output",
    "parse_pi_output",
    "run_probe",
]
