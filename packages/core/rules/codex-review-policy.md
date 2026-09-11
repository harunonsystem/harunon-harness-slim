---
description: Codex レビュー運用ポリシー。有限リソース保護、1 回実行制限、ユーザー判断の義務化。独断再レビュー禁止。/codex:review 実施前に明示 Read する（paths ゲートで非常駐。自動ロードはポリシー自体を編集する時のみ）。
paths:
  - "**/codex-review-policy.md"
---

## Codex Review Policy

**Codex は有限リソース。Claude は独断で消費しない。**

### 原則

| 原則 | 基準 |
| --- | --- |
| レビューは 1 回まで | push 前に `/codex:review` を 1 回だけ実行する |
| 結果はユーザーに提示 | 指摘があったら修正可否をユーザーに仰ぐ |
| 独断再実行禁止 | ユーザーの明示的指示なしに 2 周目を回さない |
| 明示指示があれば対応 | ユーザーが「全対応して再レビュー」と指示した場合のみ |
| bypass も独断禁止 | `~/.claude/hooks/codex-review-bypass.sh` を叩く前にユーザーに必ず聞く |
| companion は sandbox 外で実行 | `codex-companion.mjs`（review / task）と `codex app-server` は Bash sandbox 内だと sqlite state runtime init に失敗する（syscall 制限。2026-07-11 実測）。必ず sandbox を外して実行する |
| credit 枯渇・API 失敗はループしない | workspace credit 切れや接続失敗で review が返らなかったら、その旨を明言して止まる。再試行を繰り返さず、ユーザーに「手動 diff review で代替するか / bypass を承認するか」を確認する。review 未実施のまま「レビュー済み」とは書かない |

### 適用範囲

| 変更内容 | codex review |
| --- | --- |
| コード（src / hooks / scripts / 設定 JSON 等）を含む push・PR | 必須 |
| docs / rules / メモリ等の Markdown のみの変更（harness の rules 追記、ADR、README 等） | 免除。そのまま push してよい |
| 判断に迷う混合変更 | 独断で免除にせず、ユーザーに「review を挟むか」を確認 |

免除は「レビュー不要」であって「検証不要」ではない。harness の場合は validate-harness / unittest を通してから push する。

### 機械判定（review-router）

`hooks/lib/review-router.sh` の `review_route` が diff を機械分類し、`block-pr-without-codex-review.sh`（PR gate）と `block-commit-without-difit.sh`（commit 前 difit gate）に接続されている。分類優先順位は none > bypass > difit > review。

| route | 判定基準 | 挙動 |
| --- | --- | --- |
| none | 全ファイルが `*.md`/`*.mdx`/`*.txt`（拡張子判定。`docs/` 配下でもコードはレビュー対象） | PR gate: legacy flag 判定なしで allow |
| bypass | 全ファイルが lockfile/snapshot/生成物、または全コミット件名が `Revert ` 始まり | PR gate: `auto: bypass` として gate flag 自動設定 + allow |
| difit | 変更ファイル数 >= 10、変更行数 >= 400、または `components/`・`designsystems/` 配下を含む | commit gate: `/difit` 未実施なら deny（`~/.claude/hooks/difit-skip.sh "理由"` でスキップ可） |
| review | それ以外（code+docs 混合含む） | 従来どおり Codex レビュー必須 |

上記「適用範囲」表の運用ルールをこの機械分類が代替するわけではない。none/bypass は router が自動判定し、review/difit は引き続き人間の判断（本節冒頭の標準フロー）に従う。

### 標準フロー

1. push 前に `/pre-review-check`（推奨。差分に適用する観点を選び、必要な場合だけ重複・簡素化の補助チェックを使う）
2. `/codex:review` を **1 回**だけ実行
3. レビュー結果をユーザーに提示
4. ユーザーの選択肢:
   - **そのまま push**: 指摘は別タスクや別 PR に回す（P3 や scope 外は基本これ）
   - **指定指摘だけ対応**: ユーザーが優先度を決める → 修正後 push（再レビューしない）
   - **全件対応 + 再レビュー**: ユーザーが明示的に要求した場合のみ 2 周目
     - hook が 2 回目をブロックする仕組みなので、再実行するには flag ファイル `$CODEX_REVIEW_FLAG_DIR/.codex-review-done-$KEY`（既定 `~/.claude/review-gate/`）を削除する（`KEY` は git-root + branch の shasum。算出方法は下記）
5. ユーザーの指示に従い push / PR 作成

### PR Gate と Review Gate の違い

2 つの別々の gate が存在する。混同しない:

| Gate | 目的 | bypass 方法 |
| --- | --- | --- |
| Review Gate (`block-repeated-codex-review.sh`) | Codex レビューの 2 回目以降を防ぐ | `~/.claude/review-gate/.codex-review-done-$KEY` 削除（ユーザー指示要） |
| PR Gate (`block-pr-without-codex-review.sh`) | `gh pr create` 前に Codex レビュー未実施を防ぐ | `~/.claude/hooks/codex-review-bypass.sh "理由"` を実行（ログ記録、ユーザー指示要） |

**`$KEY` の算出**: git リポジトリのルートパスと現在のブランチ名から算出する（レビューサイクル＝repo + branch 単位。別ブランチの過去レビューが新しいブランチの初回レビューをブロックしないため）。hook 内部（`hooks/lib/review-gate.sh`）で算出されるため、ユーザーが手動でパスを構築する場合は `KEY=$(printf '%s\n%s\n' "$(git rev-parse --show-toplevel)" "$(git rev-parse --abbrev-ref HEAD)" | shasum | cut -d' ' -f1)` で再現できる。

done flag は記録時の HEAD を 2 行目に保持する。同名ブランチを削除→再作成した場合、記録済み HEAD が現在の履歴の祖先でなくなる（stale）ため `block-repeated-codex-review.sh` が自動的に flag を削除して初回レビューとして通す。レビュー後にコミットを積んだだけ（同一サイクルの継続）は記録済み HEAD が依然祖先なので deny を維持する。

### 禁止事項

- レビュー結果を見て Claude が独断で修正 → 再レビュー、の自動ループ
- 「すべて対応した体」で push / PR を作る
- bypass token をユーザー確認なしに取得する
- 「3 回までならループしていい」という誤解（閾値は 1 回）

### 関連ファイル

- `skills/pre-review-check/SKILL.md`: レビュー前の自己チェックと、必要時の補助チェック
- `hooks/*`: Codex レビューの 2 回目以降を機械的にブロックする PreToolUse hook
