# 公開承認（Standing Consent）と PR 連携

## 1. 恒常的公開承認（Standing Publication Consent）

リクエストされた作業範囲内で、commit、通常の push、または PR 作成を再度尋ねる前に、インストール済みの global consent を確認する。

```bash
printf '%s' 'git commit -m "task change"' | python3 <skill-dir>/scripts/harness.py consent git.commit
printf '%s' 'git push origin HEAD:refs/heads/feature' | python3 <skill-dir>/scripts/harness.py consent git.push
printf '%s' 'gh pr create --repo owner/repo --head feature --base main --body-file final-body.md' | python3 <skill-dir>/scripts/harness.py consent pr.create
```

Claude の worktree-isolated セッションではテキスト内に `git` が含まれると拒否されるため、コマンドをファイルに書き出してから渡す:
`python3 <skill-dir>/scripts/harness.py consent git.commit < /abs/path/command.txt`

`allowed: true` の場合のみユーザー確認を省略して再利用可能。保護ブランチ、force push、削除、タグ、PR head が main/master の場合は standing consent の対象外。

## 2. PR 作成前の本文・参照アテステーション

PR 本文の執筆前に `rules/pr-body.md` を読む。推敲には Agent Skill `slop-word-refactor --domain business` を適用する。

アテステーション JSON を diff 外に保存する:
```json
{
  "taskId": "<task-id>",
  "subjectSha": "<sha>",
  "bodyFile": "<path>",
  "target": { "action": "pr.create" },
  "checks": {
    "rule": "<absolute-path-to-pr-body.md>",
    "slop-word-refactor": { "mode": "applied", "domain": "business", "references": ["<slop-word-refactor/SKILL.md>"] },
    "showMe": { "mode": "unnecessary", "reason": "..." }
  }
}
```

カーネルに添付する:
```bash
python3 <skill-dir>/scripts/harness.py attach-publication-body --revision <revision> --artifact <body-attestation.json>
python3 <skill-dir>/scripts/harness.py authorize pr.create --body-file <final-body.md>
```

## 3. 自 PR へのコメント・本文更新

現在の worktree の open PR に対するコメント投稿や本文更新は narrow route を使用する:

```bash
python3 <skill-dir>/scripts/harness.py --repo <worktree> own-pr comment \
  --hostname <github-host> --repository <owner/repo> --pr <number> \
  --task-id <current-task-id> --body-file <final-comment.md>
```
