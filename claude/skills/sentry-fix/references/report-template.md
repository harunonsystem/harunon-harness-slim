# Sentry Fix 調査レポート形式

調査完了後、以下の形式で出力する。

```markdown
## Production error reconstruction

### Provider / telemetry
- Provider: Sentry
- URL: <redacted if necessary>
- Commit: <sha> (source: <field>)
- Artifact: <filename>:<lineno>:<colno or ->
- Function: <function or ->
- Release / environment: <value>

### Build
- Framework: <Next.js | Vite | other | unknown>
- Command: <actual command>
- Result: passed | failed | skipped
- Duration: <measured duration>
- Workspace / recipe: <package and actual build recipe>
- Environment differences: <list or none>
- Source Maps: confirmed generated locally | not observed | unknown; external upload: not observed | blocked | unknown

### Location evidence
- Resolved artifact: <path or not found>
- Matching line: <line and redacted context>
- Source candidate: <path:line or unknown>
- Confidence: high | medium | low

### Diagnosis
- <observed facts>
- <ranked cause hypotheses, if enough evidence exists>

### Gaps / limitations
- <missing telemetry, build failure, path mismatch, or environment caveat>
```

「修正可能」と断定するのは、原因と変更箇所を evidence から説明できる場合だけにする。build が速くても、成功していない build や別 commit の生成物を根拠にしない。
