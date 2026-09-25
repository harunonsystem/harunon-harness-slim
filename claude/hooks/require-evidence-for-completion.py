#!/usr/bin/env python3
"""Stop — 根拠のない完了・テスト通過の宣言を止める。

core-standards の「done / テスト通った / CI green は同じ turn でそのコマンドを実行し
生出力を見た場合にだけ書く」を機械的に確かめる。本文(コードを除く)に完了・通過の宣言が
あり、次のどちらかに当たれば decision: block で書き直しを指示する。

- このターンで tool を 1 度も実行していない(前の turn の結果や推測に基づく宣言)
- このターンで最後に実行したテストコマンドの出力が失敗を示している

書き直し中(stop_hook_active)は止めない(無限ループ防止)。読めない入力は素通りする(fail-open)。
"""
import json
import re
import sys

CODE_FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
BLOCKQUOTE = re.compile(r"^>.*$", re.M)
CLAIM = re.compile(
    r"完了しました|完了です|対応済みです"
    r"|テスト\s*(?:が|は)?\s*(?:すべて|全て|全部)?\s*(?:通りました|通った|通過しました|パスしました|pass)"
    r"|CI\s*(?:が|は)?\s*(?:green|グリーン|通りました|通った)"
    r"|\ball (?:tests )?pass(?:ed)?\b|\btests? pass(?:ed)?\b",
    re.I,
)
# テストを「実行する」コマンドだけを見る（`rg test` や `git add scripts/tests` は対象外）。
TEST_COMMAND = re.compile(
    r"\b(?:pytest|vitest|jest|rspec|unittest|run-tests(?:\.py)?)\b|node --test"
    r"|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|\b(?:go|cargo|mise run)\s+test\b"
)
TEST_FAILURE = re.compile(r"\b[1-9]\d* (?:failed|failing|failures?)\b|\bFAILED\b|^FAIL:", re.M)


def is_user_prompt(entry: dict) -> bool:
    """tool_result ではない、人が送った発話か。"""
    if entry.get("type") != "user":
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") != "tool_result" for block in content
    )


def result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content if isinstance(content, str) else ""


def read_turn(transcript_path: str) -> tuple[str, int, bool | None]:
    """最後のユーザー発話以降の (本文, tool 実行回数, 最後のテスト実行が失敗したか) を返す。

    テストを実行していなければ 3 つ目は None。
    """
    with open(transcript_path, encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh if line.strip()]
    start = 0
    for index in range(len(entries) - 1, -1, -1):
        if is_user_prompt(entries[index]):
            start = index + 1
            break
    texts: list[str] = []
    tool_calls = 0
    test_ids: set[str] = set()
    last_test_failed = None
    for entry in entries[start:]:
        content = entry.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if entry.get("type") == "assistant" and kind == "text":
                texts.append(block.get("text", ""))
            elif entry.get("type") == "assistant" and kind == "tool_use":
                tool_calls += 1
                command = (block.get("input") or {}).get("command", "")
                if isinstance(command, str) and TEST_COMMAND.search(command):
                    test_ids.add(block.get("id", ""))
            elif kind == "tool_result" and block.get("tool_use_id") in test_ids:
                last_test_failed = bool(block.get("is_error")) or bool(TEST_FAILURE.search(result_text(block)))
    return "\n".join(texts), tool_calls, last_test_failed


def claims(text: str) -> list[str]:
    for pattern in (CODE_FENCE, INLINE_CODE, BLOCKQUOTE):
        text = pattern.sub(" ", text)
    return sorted({match.group(0) for match in CLAIM.finditer(text)})


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("stop_hook_active"):
            return 0
        path = payload.get("transcript_path")
        if not path:
            return 0
        text, tool_calls, last_test_failed = read_turn(path)
        last = payload.get("last_assistant_message") or ""
        # Stop 時点で最後の本文が transcript に未 flush のことがある。
        if last and last not in text:
            text = f"{text}\n{last}"
    except Exception:
        return 0
    found = claims(text)
    if not found:
        return 0
    quoted = "、".join(f"「{claim}」" for claim in found)
    if tool_calls == 0:
        reason = (
            f"{quoted}と書いていますが、このターンでは tool を 1 度も実行していません。"
            "前の turn の結果や推測で完了・通過を宣言せず、検証コマンドを今実行して出力を確認してから報告するか、"
            "未検証であることを明記して書き直してください。"
        )
    elif last_test_failed:
        reason = (
            f"{quoted}と書いていますが、このターンで最後に実行したテストの出力は失敗を示しています。"
            "失敗を直して再実行するか、FAIL として報告し直してください。"
        )
    else:
        return 0
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
