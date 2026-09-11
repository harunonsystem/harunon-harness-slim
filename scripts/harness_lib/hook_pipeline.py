"""hook-pipeline.json（SSOT）と各 runtime の実体の一致を検証する。

hook-pipeline.json は pi / omp / opencode（hookRunner）と codex（codex_hook.py）が
実行時に読む。したがってこれら runtime に「hook 一覧」の実体は無く、照合するのは
(a) table が配線する hook 実体（claude-hooks/*.sh）が distribute 宣言で届くこと、
(b) hook 一覧をコードに再ハードコードしていないこと、の 2 点。claude だけは
settings.json が独自に hook を並べるため、PreToolUse を読んで membership を照合する。

interface:
    load(repo_root) -> dict
    pipeline(table, runtime) -> list[str]   # order 昇順の file 名
    check(repo_root) -> list[Finding]       # 空なら整合
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import load_target
from .jsonio import load_json_object
from .policy_kernel import TableSpec, check_table
from .validator_registry import Finding

# hooks/ に置かれるが hook として配線されない、ユーザーが手で叩く補助スクリプト。
# hook-pipeline の配線照合と distribution_sources の未参照検出の両方で除外する（SSOT）。
MANUAL_HOOK_SCRIPTS = frozenset(
    {"codex-review-bypass.sh", "codex-review-reset.sh", "difit-skip.sh", "approve-push.sh", "approve-pr.sh"}
)
# PostToolUse 側の補助スクリプト。hook-pipeline.json の表は PreToolUse の配線だけを扱うので
# 配線照合の対象外だが、hook-runner/post-edit.js（pi / omp / opencode）と codex_hook.py が
# 直接呼ぶため claude-hooks/ に配布される。
POST_TOOL_HOOK_SCRIPTS = frozenset({"post-edit-checks.sh"})


TABLE_REL = "packages/core/policy/hook-pipeline.json"

_CODEX_DISPATCHER = "packages/runtimes/codex/harunon-core/scripts/codex_hook.py"
_CODEX_BUILDER = "scripts/build-codex-plugin.py"
_CLAUDE_SETTINGS = "packages/core/settings.json"
# hookRunner とその adapter が置かれる SSOT ディレクトリ。hook 一覧の再ハードコードを禁止する範囲
_HOOK_RUNNER_JS_DIRS = (
    "packages/core/hook-runner",
    "packages/core/pi-extensions",
    "packages/core/omp-extensions",
    "packages/core/opencode-plugins",
)
# claude-hooks/ に hook 実体を配る runtime と、config.json の distribute key prefix。
# hookRunner は table を実行時に読むので、配布宣言の照合がこれら runtime の唯一の実体照合になる。
_HOOKS_DISTRIBUTE_PREFIX = {
    "pi": "claude-hooks/",
    "omp": "claude-hooks/",
    "opencode": "runtime/claude-hooks/",
}


def load(repo_root: Path) -> dict:
    return load_json_object(repo_root / TABLE_REL)


def pipeline(table: dict, runtime: str) -> list[str]:
    """runtime に配線されるべき hook file 名を order 昇順で返す。"""
    entries = [h for h in table["hooks"] if runtime in h["runtimes"]]
    entries.sort(key=lambda h: h["order"])
    return [h["file"] for h in entries]


def _validate_table(table: dict, _repo_root: Path) -> list[str]:
    errors: list[str] = []
    stages = table.get("stages") or []
    runtimes = table.get("runtimes") or {}
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()

    for hook in table.get("hooks") or []:
        hid = hook.get("id", "<no id>")
        if hid in seen_ids:
            errors.append(f"hook id が重複しています: {hid}")
        seen_ids.add(hid)

        order = hook.get("order")
        if not isinstance(order, int):
            errors.append(f"{hid}: order が整数ではありません")
        elif order in seen_orders:
            errors.append(f"{hid}: order {order} が他の hook と重複しています")
        else:
            seen_orders.add(order)

        if hook.get("stage") not in stages:
            errors.append(f"{hid}: stage が stages に含まれていません: {hook.get('stage')}")

        if "required" in hook and not isinstance(hook["required"], bool):
            errors.append(f"{hid}: required は真偽値である必要があります")

        declared = set(hook.get("runtimes") or [])
        absent = set((hook.get("absent") or {}).keys())
        unknown = (declared | absent) - set(runtimes)
        if unknown:
            errors.append(f"{hid}: 未知の runtime: {sorted(unknown)}")
        overlap = declared & absent
        if overlap:
            errors.append(f"{hid}: runtimes と absent の両方に含まれています: {sorted(overlap)}")
        missing = set(runtimes) - declared - absent
        if missing:
            errors.append(
                f"{hid}: {sorted(missing)} について配線するか absent で理由を宣言してください"
            )
        for runtime, reason in (hook.get("absent") or {}).items():
            if not str(reason).strip():
                errors.append(f"{hid}: absent[{runtime}] の理由が空です")

    return errors


def _check_stage_order(table: dict) -> list[str]:
    """逐次実行 runtime で guard が rewrite より前に来ることを保証する。"""
    errors: list[str] = []
    stage_rank = {name: i for i, name in enumerate(table["stages"])}
    by_file = {h["file"]: h for h in table["hooks"]}

    for runtime, spec in table["runtimes"].items():
        if spec.get("executionModel") != "sequential":
            continue
        ranks = [stage_rank[by_file[f]["stage"]] for f in pipeline(table, runtime)]
        if ranks != sorted(ranks):
            errors.append(
                f"{runtime}: 逐次実行 runtime で stage 順序が崩れています"
                f"（guard は rewrite より前でなければならない）"
            )
    return errors


def _codex_hardcodes_hooks(repo_root: Path, rel: str) -> bool:
    """codex 側が hook 一覧を再ハードコードしていないか。

    dispatcher と builder はどちらも table から導出する。ここに一覧が戻ると
    「片側だけ更新して集合が一致しているように見える」状態が復活するため禁止する。
    """
    text = (repo_root / rel).read_text(encoding="utf-8")
    return re.search(r"CODEX_HOOKS\s*=\s*\(", text) is not None


def _parse_claude(repo_root: Path) -> set[str]:
    """settings.json の PreToolUse.hooks[].command から呼び出される *.sh のファイル名。"""
    data = json.loads((repo_root / _CLAUDE_SETTINGS).read_text(encoding="utf-8"))
    names: set[str] = set()
    for entry in data.get("hooks", {}).get("PreToolUse", []):
        for hook in entry.get("hooks", []):
            command = hook.get("command", "")
            leaf = command.rsplit("/", 1)[-1].split()[0] if command else ""
            if leaf.endswith(".sh"):
                names.add(leaf)
    return names


# -- Policy Kernel 適合: TableSpec へ委譲するための薄いアダプタ ---------------


def _check_stage_order_table(table: dict, _repo_root: Path) -> list[str]:
    return _check_stage_order(table)


def _check_codex_hardcode_table(table: dict, repo_root: Path) -> list[str]:  # noqa: ARG001
    errs: list[str] = []
    for rel in (_CODEX_DISPATCHER, _CODEX_BUILDER):
        if _codex_hardcodes_hooks(repo_root, rel):
            errs.append(
                f"{rel}: hook 一覧が再ハードコードされています。"
                f"hook-pipeline.json から導出してください"
            )
    return errs


def _check_js_hardcode_table(table: dict, repo_root: Path) -> list[str]:  # noqa: ARG001
    """hookRunner / adapter に hook 一覧（const HOOKS = [...]）が戻っていないか。

    2026-09-03 以前は opencode の bridge が HOOKS 配列を持ち、validator が JS ソースを
    正規表現で逆パースして table と突き合わせていた。table が実行の source になった今、
    一覧がコードに戻ること自体を禁止する（codex の CODEX_HOOKS と同じ規律）。
    """
    errs: list[str] = []
    for rel in _HOOK_RUNNER_JS_DIRS:
        for path in sorted((repo_root / rel).glob("*.[jt]s")):
            if re.search(r"const\s+HOOKS\s*=\s*\[", path.read_text(encoding="utf-8")):
                errs.append(
                    f"{path.relative_to(repo_root)}: hook 一覧が再ハードコードされています。"
                    f"hook-pipeline.json を実行時に読んでください"
                )
    return errs


def _check_hook_distribute_table(table: dict, repo_root: Path) -> list[str]:
    """<target>/config.json の claude-hooks/*.sh 配布宣言が table の配線と一致するか。

    hookRunner は table から配線を決めるので、実体側で照合できるのは「配線された hook が
    配布経路（distribute エントリ）で届くか」だけ。table にだけ追加して config.json を
    更新し忘れる distribution gap を検出する。
    """
    errors: list[str] = []
    for target, prefix in _HOOKS_DISTRIBUTE_PREFIX.items():
        config_rel = f"packages/targets/{target}/config.json"
        # config.json の不在・不正は config-schema check の責務。ここで例外を漏らすと
        # validate-harness 全体が finding を返さず abort する。
        try:
            config = load_target(target, repo_root)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(f"{config_rel}: 読み込めないため配布宣言を照合できません（{exc}）")
            continue
        distribute = config.get("distribute") or {}
        distributed = {
            key[len(prefix):]
            for key in distribute
            if key.startswith(prefix)
            and key.endswith(".sh")
            and "/" not in key[len(prefix):]
        } - MANUAL_HOOK_SCRIPTS - POST_TOOL_HOOK_SCRIPTS
        expected = set(pipeline(table, target))

        missing_from_config = expected - distributed
        extra_in_config = distributed - expected
        if missing_from_config:
            errors.append(
                f"{config_rel}: table が {target} に配線する hook が distribute に無い: "
                f"{sorted(missing_from_config)}"
            )
        if extra_in_config:
            errors.append(
                f"{config_rel}: table に {target} 配線が無い {prefix}*.sh が distribute にある: "
                f"{sorted(extra_in_config)}"
            )
    return errors


def _check_claude_table(table: dict, repo_root: Path) -> list[str]:
    errs: list[str] = []
    claude_actual = _parse_claude(repo_root)
    for expected in pipeline(table, "claude"):
        if expected not in claude_actual:
            errs.append(
                f"{_CLAUDE_SETTINGS}: table が claude に宣言する {expected} が "
                f"PreToolUse に登録されていません"
            )
    return errs


_HOOK_SPEC = TableSpec(
    name="hook-pipeline",
    table_rel=TABLE_REL,
    validate=_validate_table,
    checks=[
        _check_stage_order_table,
        _check_codex_hardcode_table,
        _check_js_hardcode_table,
        _check_hook_distribute_table,
        _check_claude_table,
    ],
)


def check(repo_root: Path) -> list[Finding]:
    """hook-pipeline.json SSOT table と各 runtime の実体の一致を検証する.

    Policy Kernel (TableSpec + check_table) へ委譲する thin wrapper。
    """
    return check_table(repo_root, _HOOK_SPEC)
