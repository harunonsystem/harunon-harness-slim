"""Human-readable output adapter for Distribution plans and results."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
from typing import Callable

from .distribution_state import (
    ApplyResult,
    ApplyStatus,
    DistributionInspection,
    DistributionPlan,
    Operation,
    OperationStatus,
)


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def _effective_operations(plan: DistributionPlan, result: ApplyResult):
    by_index = {event.index: event for event in result.events}
    for index, operation in enumerate(plan.operations):
        event = by_index.get(index)
        if event is None or event.status in {OperationStatus.APPLIED, OperationStatus.PLANNED}:
            yield operation


_PUSH_BUCKET_NAMES = (
    "added", "updated", "mode_unfixable", "removed_obsolete", "removed_managed", "pruned", "mode_fixed",
)


def _settings_keys(operation: Operation) -> str:
    change = operation.change
    if change is None:
        return ""
    return ", ".join(list(change.changed) + [f"-{key}" for key in change.removed])


def _line_backup(plan: DistributionPlan, op: Operation) -> str | None:
    if op.skip_dry_run_line:
        return None
    return f"DRY: backup {plan.destination_path / op.path} -> {Path(op.backup_path or '').parent}/"


def _line_settings_sync(plan: DistributionPlan, op: Operation) -> str:
    keys = _settings_keys(op)
    if plan.dry_run:
        return f"DRY: settings-sync update {op.path}（{keys}）"
    return f"settings-sync: {op.path} の {keys} を同期"


def _line_settings_overlay(plan: DistributionPlan, op: Operation) -> str:
    keys = _settings_keys(op)
    label = op.change.label if op.change is not None else op.metadata_map.get("label", "")
    if plan.dry_run:
        return f"DRY: settings-sync {label} update {op.path}（{keys}）"
    return f"settings-sync {label}: {op.path} の {keys} を同期"


def _line_extras_overlay(plan: DistributionPlan, op: Operation) -> str:
    return f"DRY: merge {op.metadata_map.get('overlay', '')} from {op.metadata_map.get('extra', '')} into settings.json"


_SIMPLE_LABELS = {
    "add": "add",
    "overwrite": "overwrite",
    "chmod": "chmod +x",
    "prune": "prune",
}


def _line_simple(plan: DistributionPlan, op: Operation) -> str:
    return f"DRY: {_SIMPLE_LABELS[op.kind]} {op.path}"


_PUSH_LINES: dict[str, Callable[[DistributionPlan, Operation], str | None]] = {
    "backup": _line_backup,
    "add": _line_simple,
    "overwrite": _line_simple,
    "chmod": _line_simple,
    "prune": _line_simple,
    "settings-template": lambda plan, op: f"DRY: settings-sync add {op.path}（template 全体）",
    "settings-sync": _line_settings_sync,
    "settings-overlay": _line_settings_overlay,
    "extras-overlay": _line_extras_overlay,
}
_ALWAYS_REPORTED = {"settings-sync", "settings-overlay"}


def _render_push_result(plan: DistributionPlan, result: ApplyResult) -> int:
    if result.status in {ApplyStatus.STALE, ApplyStatus.INVALID, ApplyStatus.PARTIAL_FAILURE}:
        if result.error:
            _warn(f"ERROR: {result.error}")
        return result.exit_code

    buckets: dict[str, list[str]] = {name: [] for name in _PUSH_BUCKET_NAMES}
    for operation in _effective_operations(plan, result):
        bucket = operation.bucket
        if bucket is not None:
            buckets[bucket].append(operation.path)
        if plan.dry_run or operation.kind in _ALWAYS_REPORTED:
            formatter = _PUSH_LINES.get(operation.kind)
            line = formatter(plan, operation) if formatter else None
            if line is not None:
                print(line)

    summary = plan.summary
    if plan.dry_run:
        for rel in summary.disabled_plugin_files:
            print(f"DRY: skip disabled plugin {rel}")
    for warning in plan.warnings:
        _warn(f"WARN: {warning}")

    print(f"added: {len(buckets['added'])}")
    print(f"updated: {len(buckets['updated'])}")
    print(f"unchanged: {summary.unchanged_count}")
    print(f"mode fixed: {len(buckets['mode_fixed'])}")
    print(f"removed obsolete: {len(buckets['removed_obsolete'])}")
    print(f"removed managed stale: {len(buckets['removed_managed'])}")
    print(f"preserved modified stale: {len(summary.modified_stale_paths)}")
    if summary.pruned_backups:
        print(f"pruned backups: {len(summary.pruned_backups)}")
    if plan.prune:
        print(f"pruned: {len(buckets['pruned'])}")
        for path in buckets["pruned"]:
            print(f"  [pruned]  {path}")
    for path in buckets["added"]:
        print(f"  [added]   {path}")
    for path in buckets["updated"]:
        print(f"  [updated] {path}")
    for path in buckets["mode_fixed"]:
        print(f"  [mode]    {path}")
    for path in buckets["mode_unfixable"]:
        _warn(
            f"WARN: {path} は symlink で参照先が非実行。chmod は参照先（SSOT 側）に及ぶため"
            "補正していない。symlink を管理コピーに置き換えろ"
        )
    for path in summary.modified_stale_paths:
        print(f"  [preserved-modified] {path}")
    if buckets["updated"]:
        prefix = "DRY: " if plan.dry_run else ""
        print(f"{prefix}⚠️  {len(buckets['updated'])} 件の既存ファイルを上書きしました（backup: {plan.backup_base or ''}）")
        print("   ライブ側の修正が意図的だった場合は backup から harness へ還流してください（SSOT-first 原則）")
    for path in buckets["removed_obsolete"]:
        print(f"  [obsolete] {path}")
    for path in buckets["removed_managed"]:
        print(f"  [removed-managed] {path}")
    return result.exit_code


def _render_pull_result(plan: DistributionPlan, result: ApplyResult) -> int:
    if result.status in {ApplyStatus.STALE, ApplyStatus.INVALID}:
        if result.error:
            _warn(f"ERROR: {result.error}")
        return result.exit_code
    pulled: list[str] = []
    skipped: list[tuple[str, str]] = []
    for operation in _effective_operations(plan, result):
        if operation.kind == "pull":
            source = plan.repo_path / (operation.source_path or "")
            try:
                display_source = source.relative_to(plan.repo_path).as_posix()
            except ValueError:
                display_source = source.as_posix()
            if not plan.dry_run:
                print(f"  [pulled]  {operation.path} -> {display_source}")
            details = operation.metadata_map
            existing = int(details.get("existingSources", "0"))
            if existing > 1:
                print(f"  ⚠️ {operation.path}: core/extras 両方に存在。{details.get('winningSource', '')} に書き戻した")
            elif existing == 0:
                print(
                    f"  ⚠️ {operation.path}: どの source にも存在しない新規ファイル。"
                    f"先頭 source（{details.get('winningSource', '')}）に作成した"
                )
            if plan.dry_run:
                print(f"DRY: pull {operation.path} -> {display_source}")
            pulled.append(operation.path)
        elif operation.kind == "pull-skip":
            skipped.append((operation.path, operation.reason or "skip"))
    if result.error:
        _warn(f"ERROR: {result.error}")
    if not pulled and not skipped:
        print("OK: drift なし。pull するものなし")
        return result.exit_code
    print(f"\npulled: {len(pulled)}, skipped: {len(skipped)}")
    for path, reason in skipped:
        print(f"  [skipped] {path}: {reason}")
    return result.exit_code


def render_result(plan: DistributionPlan, result: ApplyResult) -> int:
    if plan.operation == "push":
        return _render_push_result(plan, result)
    if plan.operation == "pull":
        return _render_pull_result(plan, result)
    if result.error:
        _warn(f"ERROR: {result.error}")
    return result.exit_code


def render_inspection(inspection: DistributionInspection) -> int:
    if not inspection.destination_exists:
        print(f"live ディレクトリが存在しません: {inspection.destination}")
        return 1
    if not inspection.drifts:
        print("OK")
        return 0
    for drift in inspection.drifts:
        print(f"  [{drift.kind}] {drift.path}")
    kind_counts = Counter(drift.kind for drift in inspection.drifts)
    counts = ", ".join(f"{kind}: {count}" for kind, count in sorted(kind_counts.items()))
    print(f"\n差分あり: {len(inspection.drifts)} 件（{counts}）")
    return 1
