#!/usr/bin/env python3
"""Compare harness capabilities from repository evidence only.

Offline reconciliation is the default.  ``--no-live`` is accepted as an
explicit spelling for scripts that make the offline boundary visible; this
command never reads live runtime configuration or uses a network.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from harness_lib import capabilities, live_capabilities  # noqa: E402


def _parse_targets(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _validate_requested_targets(
    requested: list[str] | None, available: list[str], parser: argparse.ArgumentParser
) -> None:
    if requested is None:
        return
    unknown = sorted(set(requested) - set(available))
    if unknown:
        parser.error("unknown runtime target(s): " + ", ".join(unknown))


def _verdict(report: dict, target: str, dimension: str) -> str:
    claim = report.get("claims", {}).get(target, {}).get(dimension, {})
    return str(claim.get("verdict", "—"))


def _terminal(report: dict) -> str:
    if report.get("mode") == "live":
        return _live_terminal(report)
    dimensions = report["dimensions"]
    headers = ["Target", *dimensions]
    rows = [[target, *[_verdict(report, target, dim) for dim in dimensions]] for target in report["targets"]]
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    lines = ["Capability bench (offline)"]
    lines.append("  ".join(value.ljust(width) for value, width in zip(headers, widths)))
    lines.append("  ".join("-" * width for width in widths))
    lines.extend("  ".join(value.ljust(width) for value, width in zip(row, widths)) for row in rows)
    if report["findings"]:
        lines.append("")
        lines.append(f"Findings: {len(report['findings'])}")
        lines.extend(f"[{finding.level.upper()}] {finding.code}: {finding.message}" for finding in report["findings"])
    else:
        lines.append("")
        lines.append("OK: static evidence reconciled")
    return "\n".join(lines) + "\n"


def _live_terminal(report: dict) -> str:
    lines = ["Capability bench (live)", "Target  Probe             Status   Reason"]
    lines.append("------  ----------------  -------  ------")
    for observation in report["observations"]:
        lines.append(
            "  ".join(
                (
                    observation["target"].ljust(6),
                    observation["probe"].ljust(16),
                    observation["status"].ljust(7),
                    observation.get("reason") or "",
                )
            )
        )
    counts = {status: 0 for status in live_capabilities.STATUSES}
    for observation in report["observations"]:
        counts[observation["status"]] += 1
    lines.extend(
        (
            "",
            "Summary: "
            + ", ".join(f"{status}={counts[status]}" for status in live_capabilities.STATUSES),
        )
    )
    if report["findings"]:
        lines.append(f"Findings: {len(report['findings'])}")
        lines.extend(
            f"[{finding.level.upper()}] {finding.code}: {finding.message}"
            for finding in report["findings"]
        )
    return "\n".join(lines) + "\n"


def _markdown(report: dict) -> str:
    if report.get("mode") == "live":
        return _live_markdown(report)
    dimensions = report["dimensions"]
    lines = [
        "<!-- capability-bench: offline static evidence; live behavior is not proven -->",
        "| Target | " + " | ".join(dimensions) + " |",
        "| --- | " + " | ".join("---" for _ in dimensions) + " |",
    ]
    lines.extend(
        "| " + target + " | " + " | ".join(_verdict(report, target, dim) for dim in dimensions) + " |"
        for target in report["targets"]
    )
    if report["findings"]:
        lines.extend(("", f"Findings: {len(report['findings'])}"))
        lines.extend(
            f"- `{finding.code}`: {finding.message}"
            for finding in report["findings"]
        )
    return "\n".join(lines) + "\n"


def _live_markdown(report: dict) -> str:
    lines = [
        "<!-- capability-bench: live runtime observations; static wiring remains separate -->",
        "| Target | Probe | Status | Reason |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        "| {target} | {probe} | {status} | {reason} |".format(
            target=observation["target"],
            probe=observation["probe"],
            status=observation["status"],
            reason=(observation.get("reason") or "").replace("|", "\\|")
        )
        for observation in report["observations"]
    )
    if report["findings"]:
        lines.extend(("", f"Findings: {len(report['findings'])}"))
        lines.extend(
            f"- `{finding.code}`: {finding.message}"
            for finding in report["findings"]
        )
    return "\n".join(lines) + "\n"


def _json(report: dict) -> str:
    if report.get("mode") == "live":
        payload = {
            "schemaVersion": report["schemaVersion"],
            "mode": report["mode"],
            "targets": report["targets"],
            "dimensions": report["dimensions"],
            "probes": report["probes"],
            "observations": report["observations"],
            "findings": [asdict(finding) for finding in report["findings"]],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    # Keep this envelope intentionally small and key-ordered for scripts.
    payload = {
        "schemaVersion": report["schemaVersion"],
        "mode": report["mode"],
        "targets": report["targets"],
        "dimensions": report["dimensions"],
        "claims": report["claims"],
        "findings": [asdict(finding) for finding in report["findings"]],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare harness capability claims from static or live evidence"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_SCRIPTS_DIR.parent,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--targets",
        help="Comma-separated runtime target names (default: all runtime targets)",
    )
    parser.add_argument(
        "--format",
        choices=("terminal", "json", "markdown"),
        default="terminal",
        help="Output format (default: terminal)",
    )
    live_group = parser.add_mutually_exclusive_group()
    live_group.add_argument(
        "--live",
        action="store_true",
        help="Run bounded live probes for selected runtime targets",
    )
    live_group.add_argument(
        "--no-live",
        action="store_true",
        help="Explicitly select the default offline static mode",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Per-probe live timeout in seconds (default: 30)",
    )
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    requested = _parse_targets(args.targets)
    available = capabilities.runtime_targets(args.repo_root)
    _validate_requested_targets(requested, available, parser)
    report = (
        live_capabilities.live_reconcile(
            args.repo_root,
            targets=requested,
            timeout_seconds=args.timeout_seconds,
        )
        if args.live
        else capabilities.reconcile(args.repo_root, targets=requested)
    )
    if args.format == "json":
        output = _json(report)
    elif args.format == "markdown":
        output = _markdown(report)
    else:
        output = _terminal(report)
    sys.stdout.write(output)
    return 1 if capabilities.has_errors(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
