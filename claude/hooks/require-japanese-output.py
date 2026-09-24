#!/usr/bin/env python3
"""Stop — そのターンの本文が英語に偏っていたら、日本語で書き直させる。

本文(コードブロック・インラインコード・URL・パスを除く)の英字と日本語の文字数を比べ、
英字の割合が THRESHOLD 以上なら decision: block で止めて書き直しを指示する。
書き直し中(stop_hook_active)は止めない(無限ループ防止)。読めない入力は素通りする(fail-open)。
"""
import json
import re
import sys

THRESHOLD = 0.8
# 短い応答(「完了しました。」+ パス等)は判定がぶれるので対象外。
MIN_LETTERS = 80

CODE_FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+")
PATH_LIKE = re.compile(r"\S*[/\\]\S*")
LATIN = re.compile(r"[A-Za-z]")
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
RAW_REQUEST = re.compile(
    r"\b(?:raw|verbatim|in English|English only)\b|英語で|原文のまま|逐語|そのまま(?:貼|返|出力|表示|引用|書|見せ)",
    re.I,
)


def english_ratio(text: str) -> tuple[float, int]:
    for pattern in (CODE_FENCE, INLINE_CODE, URL, PATH_LIKE):
        text = pattern.sub(" ", text)
    latin = len(LATIN.findall(text))
    japanese = len(JAPANESE.findall(text))
    total = latin + japanese
    return (latin / total if total else 0.0), latin


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


def turn_text(transcript_path: str) -> tuple[str, str]:
    """最後のユーザー発話と、それ以降に assistant が書いた本文を返す。"""
    with open(transcript_path, encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh if line.strip()]
    texts: list[str] = []
    prompt = ""
    for entry in reversed(entries):
        if is_user_prompt(entry):
            content = entry["message"]["content"]
            if isinstance(content, str):
                prompt = content
            else:
                prompt = "\n".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            break
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content")
        if isinstance(content, list):
            texts.extend(
                block.get("text", "")
                for block in reversed(content)
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return "\n".join(reversed(texts)), prompt


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("stop_hook_active"):
            return 0
        path = payload.get("transcript_path")
        last = payload.get("last_assistant_message") or ""
        try:
            text, prompt = turn_text(path) if path else ("", "")
        except Exception:
            text, prompt = "", ""
        # Stop 時点で最後の本文が transcript に未 flush のことがある(2026-09-22 に英語ターンを素通り)。
        if last and last not in text:
            text = f"{text}\n{last}"
    except Exception:
        return 0
    if RAW_REQUEST.search(prompt):
        return 0
    ratio, latin = english_ratio(text or "")
    if latin < MIN_LETTERS or ratio < THRESHOLD:
        return 0
    reason = (
        f"このターンの本文の {ratio:.0%} が英語です。ユーザーへの出力は日本語が既定です。"
        "このターンで書いた本文全体を日本語で書き直して、もう一度出力してください"
        "(コード・識別子・コマンド・パス・引用した原文は元のまま)。"
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
