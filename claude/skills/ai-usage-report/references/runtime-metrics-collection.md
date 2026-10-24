# ランタイム別メトリクス収集手順

## 1. Codex の実測

`scripts/codex-usage.py`（harness repo）を使う。

```bash
python3 <harness-repo>/scripts/codex-usage.py --since <YYYY-MM-DD>
```

`find | wc -l` は以下の理由で実態とずれる:
- `archived_sessions/` に移された過去のログが落ちる
- 1ファイル＝1セッションだが、人が始めた Codex セッションは `thread_source` が `user` の行だけ
- `"model":"..."` を grep で数えると turn_context の出現回数になる

出力の `thread_source 別` と `model × effort 別` を報告に使う。

## 2. pi / omp の実測

どちらも `sessions/<encoded-cwd>/<ISO>_<uuid>.jsonl` でファイル先頭が ISO 日付。
モデルは `model_change` イベントに入る（pi は `modelId`、omp は `model`）。

```bash
# 月別セッション数
for d in ~/.pi/agent/sessions ~/.omp/agent/sessions; do
  echo "## $d"
  find "$d" -name '*.jsonl' | perl -ne 'print "$1\n" if m{/(\d{4}-\d{2})}' | sort | uniq -c
done

# モデル構成
for d in ~/.pi/agent/sessions ~/.omp/agent/sessions; do
  echo "## $d"
  find "$d" -name '*.jsonl' \
    | xargs perl -ne 'print "$1\n" if /"type":"model_change".*?"model(?:Id)?":"([^"]+)"/' \
    | sort | uniq -c | sort -rn
done
```

omp は `<provider>/<model>` の形式。合算時は注意。

## 3. OpenCode の実測

`~/.local/share/opencode/opencode.db` と旧 `storage/session/` を確認する。DB は読み取り専用で開く。

```sql
SELECT s.id AS session_id, m.id AS message_id, p.id AS part_id,
       CASE
         WHEN json_extract(p.data, '$.type') = 'subtask' THEN 'subtask'
         WHEN json_extract(p.data, '$.synthetic') = 1 THEN 'synthetic'
         WHEN s.parent_id IS NOT NULL THEN 'child_session'
         ELSE 'direct_user_candidate'
       END AS classification
FROM session s
JOIN message m ON m.session_id = s.id
JOIN part p ON p.message_id = m.id
WHERE json_extract(m.data, '$.role') = 'user'
  AND json_extract(p.data, '$.type') IN ('text', 'subtask');
```
