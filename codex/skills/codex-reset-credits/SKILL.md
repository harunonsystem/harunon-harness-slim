---
name: codex-reset-credits
description: Codex のリセットクレジット残数と有効期限を確認する。「codex reset」「リセットクレジット」「reset credits」で起動。
references:
  - scripts/check-reset-credits.mjs
---

# codex-reset-credits

## What to Do

Run the script bundled with this skill (resolve the path relative to this SKILL.md's directory — works from any tool's distributed copy):

```bash
node <this-skill-dir>/scripts/check-reset-credits.mjs
```

The script reads Codex authentication from `~/.codex/auth.json`, calls the Codex backend reset-credit endpoint, and prints only:

- available reset credit count
- each `expires_at` value in the local timezone
- sanitized non-secret shape information only when the endpoint response shape is unknown

## Rules

- Use only `https://chatgpt.com/backend-api/wham/rate-limit-reset-credits`.
- Do not infer expiry from `dismissedAtMs`, referral docs, local UI state, screenshots, or tweets.
- Never print access tokens, refresh tokens, auth headers, cookies, or the full `~/.codex/auth.json`.
- If the endpoint returns an unknown response shape, show sanitized keys/values only and omit anything secret-like.
- State that this uses an internal ChatGPT/Codex backend endpoint and may break without notice.

