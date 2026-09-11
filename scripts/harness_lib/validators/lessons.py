"""Lesson ledger entries and their enforcement targets."""

from __future__ import annotations

import datetime as _datetime
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

from ..validator_registry import Finding


CHECK_NAME = "lessons"
LEDGER_PATH = Path("packages/core/lessons/lessons.json")
_TARGET_RE = re.compile(r"^(rule|hook|test):(.+)$")
_REQUIRED_FIELDS = {
    "id",
    "date",
    "summary",
    "source_runtime",
    "enforced_by",
    "status",
}


def _finding(lesson_id: str, level: str, message: str) -> Finding:
    return Finding(check=CHECK_NAME, level=level, message=f"{lesson_id}: {message}")


def _iter_tests(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _has_matching_heading(path: Path, anchor: str) -> bool:
    """Return True if `path` has a markdown heading whose text equals `anchor`."""
    for line in path.read_text(encoding="utf-8").splitlines():
        heading_match = re.match(r"^#+\s+(.*)$", line)
        if heading_match and heading_match.group(1).strip() == anchor:
            return True
    return False


def _test_is_collectable(repo_root: Path, test_path: Path, names: list[str]) -> tuple[bool, str]:
    """Load one test module and ask unittest to resolve its class and method.

    Returns (is_collectable, error_detail). error_detail is empty on success.
    """
    module_name = f"_harness_lesson_target_{abs(hash(str(test_path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, test_path)
    if spec is None or spec.loader is None:
        return False, "モジュールをロードできません"

    module = importlib.util.module_from_spec(spec)
    original_path = list(sys.path)
    sys.path.insert(0, str(repo_root / "scripts"))
    sys.path.insert(0, str(repo_root))
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        suite = unittest.TestLoader().loadTestsFromName(".".join(names), module)
        tests = list(_iter_tests(suite))
        if not tests:
            return False, "テストが見つかりません"
        result = unittest.TestResult()
        suite.run(result)
        if result.errors:
            _, traceback_text = result.errors[0]
            detail = traceback_text.strip().splitlines()[-1] if traceback_text else "unknown error"
            return False, detail
        return True, ""
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not swallowed
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        sys.path[:] = original_path
        sys.modules.pop(module_name, None)


def _safe_relative_path(raw: str, prefix: str) -> Path | None:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts or path.parts[:1] != (prefix,):
        return None
    return path


def _check_target(repo_root: Path, lesson_id: str, target: str) -> list[Finding]:
    if target == "pending":
        return []

    match = _TARGET_RE.fullmatch(target)
    if match is None:
        return [_finding(lesson_id, "error", f"enforced_by が不正です: {target}")]

    kind, payload = match.groups()
    if kind == "rule":
        path_raw, separator, anchor = payload.partition("#")
        relative = _safe_relative_path(path_raw, "rules")
        if relative is None or not path_raw.endswith(".md") or not separator or not anchor:
            return [_finding(lesson_id, "error", f"rule target が不正です: {target}")]
        target_path = repo_root / "packages" / "core" / relative
        if not target_path.is_file():
            return [_finding(lesson_id, "error", f"enforced_by の対象ファイルが存在しません: {target}")]
        if not _has_matching_heading(target_path, anchor):
            return [_finding(lesson_id, "error", f"rule target の anchor が見出しと一致しません: {target}")]
        return []
    elif kind == "hook":
        relative = _safe_relative_path(payload, "hooks")
        if relative is None or not payload.endswith(".sh"):
            return [_finding(lesson_id, "error", f"hook target が不正です: {target}")]
        target_path = repo_root / "packages" / "core" / relative
    else:
        parts = payload.split("::")
        relative = _safe_relative_path(parts[0], "scripts") if parts else None
        if (
            relative is None
            or not parts[0].startswith("scripts/tests/test_")
            or not parts[0].endswith(".py")
            or len(parts) < 3
            or any(not part for part in parts[1:])
        ):
            return [_finding(lesson_id, "error", f"test target が不正です: {target}")]
        target_path = repo_root / relative
        if not target_path.is_file():
            return [_finding(lesson_id, "error", f"enforced_by の対象ファイルが存在しません: {target}")]
        collectable, detail = _test_is_collectable(repo_root, target_path, parts[1:])
        if not collectable:
            return [
                _finding(
                    lesson_id,
                    "error",
                    f"test target が unittest で collectable ではありません: {target} ({detail})",
                )
            ]
        return []

    if not target_path.is_file():
        return [_finding(lesson_id, "error", f"enforced_by の対象ファイルが存在しません: {target}")]
    return []


def _check_entry(repo_root: Path, index: int, entry: object, seen_ids: set[str]) -> list[Finding]:
    label = f"lesson[{index}]"
    if not isinstance(entry, dict):
        return [_finding(label, "error", "エントリはオブジェクトである必要があります")]

    findings: list[Finding] = []
    lesson_id = entry.get("id")
    if not isinstance(lesson_id, str) or not lesson_id:
        lesson_id = label
        findings.append(_finding(label, "error", "id がありません"))
    elif lesson_id in seen_ids:
        findings.append(_finding(lesson_id, "error", "id が重複しています"))
    else:
        seen_ids.add(lesson_id)

    for field in sorted(_REQUIRED_FIELDS - entry.keys()):
        findings.append(_finding(lesson_id, "error", f"{field} がありません"))

    lesson_date = entry.get("date")
    parsed_date: _datetime.date | None = None
    if isinstance(lesson_date, str):
        try:
            parsed_date = _datetime.date.fromisoformat(lesson_date)
        except ValueError:
            findings.append(_finding(lesson_id, "error", f"date が ISO 日付ではありません: {lesson_date}"))
    else:
        findings.append(_finding(lesson_id, "error", "date は文字列である必要があります"))

    summary = entry.get("summary")
    if not isinstance(summary, str):
        findings.append(_finding(lesson_id, "error", "summary は文字列である必要があります"))
    elif len(summary) > 120:
        findings.append(_finding(lesson_id, "error", "summary は120文字以内である必要があります"))

    source_runtime = entry.get("source_runtime")
    if not isinstance(source_runtime, str) or not source_runtime:
        findings.append(_finding(lesson_id, "error", "source_runtime は空でない文字列である必要があります"))

    status = entry.get("status")
    if status not in {"pending", "enforced"}:
        findings.append(_finding(lesson_id, "error", f"status が不正です: {status}"))

    enforced_by = entry.get("enforced_by")
    if not isinstance(enforced_by, str) or not enforced_by:
        findings.append(_finding(lesson_id, "error", "enforced_by は空でない文字列である必要があります"))
    elif status == "enforced" and enforced_by == "pending":
        findings.append(_finding(lesson_id, "error", "status=enforced の enforced_by は pending にできません"))
    else:
        findings.extend(_check_target(repo_root, lesson_id, enforced_by))

    if status == "pending" and parsed_date is not None:
        age = (_datetime.date.today() - parsed_date).days
        if age > 30:
            findings.append(_finding(lesson_id, "warn", f"pending が30日を超えています（{age}日）"))
    return findings


def check_lessons(repo_root: Path) -> list[Finding]:
    """Validate the runtime-neutral lesson ledger and its enforcement targets."""
    path = repo_root / LEDGER_PATH
    if not path.is_file():
        return [_finding(str(LEDGER_PATH), "error", "lessons.json が存在しません")]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        return [_finding(str(LEDGER_PATH), "error", f"読み込みに失敗しました: {error}")]
    except json.JSONDecodeError as error:
        return [_finding(str(LEDGER_PATH), "error", f"JSON として解析できません: {error.msg}")]
    if not isinstance(data, list):
        return [_finding(str(LEDGER_PATH), "error", "root は lesson の配列である必要があります")]

    findings: list[Finding] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(data):
        findings.extend(_check_entry(repo_root, index, entry, seen_ids))
    return findings


CHECKS = {CHECK_NAME: check_lessons}

__all__ = ["CHECKS", "LEDGER_PATH", "check_lessons"]
