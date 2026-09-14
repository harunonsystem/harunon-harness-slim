---
description: Codex レビュー運用ポリシー。有限リソース保護、1 回実行制限、指摘は全件修正、quota 切れは SKIP 記録。独断再レビュー禁止。/codex:review 実施前に明示 Read する（paths ゲートで非常駐。自動ロードはポリシー自体を編集する時のみ）。
paths:
  - "**/codex-review-policy.md"
---

## Codex Review Policy

**Codex は有限リソース。Claude は独断で消費しない。**

### 原則

| 原則 | 基準 |
| --- | --- |
| レビューは 1 回まで | push 前に `/codex:review` を 1 回だけ実行する。既定は background 起動（`commands/codex/review.md`） |
| 指摘は全件修正する | 結果を提示したうえで、ユーザーの指示を待たずに P0 / P1 / P2 を全件修正する。P0 がこのブランチで直せない場合は push / PR に進まず止まって報告する。P3 と scope 外は直さず PR 本文の「残件」に列挙する。修正後の再レビューはしない |
| 独断再実行禁止 | ユーザーの明示的指示なしに 2 周目を回さない |
| 再レビューは明示指示のみ | ユーザーが「再レビュー」と指示した場合だけ 2 周目（done flag の削除が要る。下記） |
| bypass は quota 切れだけ自動 | `~/.claude/hooks/codex-review-bypass.sh` を人手の理由で叩く前はユーザーに聞く。例外は quota / credit 切れで review が返らなかった場合で、`--quota "<エラー要旨>"` で SKIP を記録して進む（ログに quota 起因と残る） |
| companion は sandbox 外で実行 | `codex-companion.mjs`（review / task）と `codex app-server` は Bash sandbox 内だと sqlite state runtime init に失敗する（syscall 制限。2026-07-11 実測）。必ず sandbox を外して実行する |
| quota 切れ・API 失敗はループしない | 再試行を繰り返さない。quota / credit 切れ（companion の出力に usage limit・insufficient quota・rate limit・429・credit の類が出て review が返らない）は `--quota` で SKIP を記録し、PR 本文に「Codex review: SKIP（quota）」と書く。接続失敗など quota 以外の失敗は止まってユーザーに「手動 diff review で代替するか / bypass を承認するか」を確認する。どちらの場合も「レビュー済み」とは書かない |

### 適用範囲

| 変更内容 | codex review |
| --- | --- |
| コード（src / hooks / scripts / 設定 JSON 等）を含む push・PR | 必須 |
| docs / rules / メモリ等の Markdown のみの変更（harness の rules 追記、ADR、README 等） | 免除。そのまま push してよい |
| 判断に迷う混合変更 | 独断で免除にせず、ユーザーに「review を挟むか」を確認 |

免除は「レビュー不要」であって「検証不要」ではない。対象リポジトリの検証コマンドを通してから push する。

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
2. `/codex:review` を **1 回**だけ実行（background 起動。完了通知が来るまで独立した作業を進める）
3. レビュー結果をユーザーに提示する（指摘は原文のまま並べる。要約で件数や優先度を変えない）
4. 指摘を全件修正する。ユーザーの選択を待たない
   - P0 / P1 / P2: 同じブランチの working tree で修正する。P0 が直せない場合は push / PR に進まず止まって報告する。修正が既存の決定や scope と衝突する場合だけ、その 1 件についてユーザーに聞く
   - 修正はレビュー対象の差分に閉じる。無関係な未 commit 変更を巻き込まない（`git add <対象ファイル>` で明示 stage する）
   - 修正の commit は通常の Git 規約どおり: 現在のタスクで commit / PR まで委任されていなければ commit 前にユーザー確認を取る。`/codex:review` の実行指示は commit の承認ではない
   - P3 / scope 外: 直さず PR 本文の「残件」に finding 単位で列挙する（別 issue に回すかはユーザー判断）
   - 修正後の再レビューはしない。PR gate はレビュー済み commit が HEAD の祖先なら通す（下記）。Core Workflow 使用中は `findings_fixed` で decide → publish に進める。同じ finding が別ブランチで 3 回続いたらアプローチを見直す
5. quota / credit 切れで review が返らなかった場合は SKIP: `~/.claude/hooks/codex-review-bypass.sh --quota "<companion のエラー要旨>"` で gate flag と理由を記録し（Core Workflow が進行中なら kernel にも `review.skip` を記録して review → publish へ進める）、PR 本文に「Codex review: SKIP（quota）」と書く。quota 以外の失敗（接続・認証・companion のクラッシュ）は止まってユーザーに確認する
6. 再レビューはユーザーが明示的に要求した場合のみ。hook が 2 回目をブロックする仕組みなので、再実行するには flag ファイル `$CODEX_REVIEW_FLAG_DIR/.codex-review-done-$KEY`（既定 `~/.claude/review-gate/`）を削除する（`KEY` は git-root + branch の shasum。算出方法は下記）
7. push / PR 作成はユーザー確認後（Git 公開操作の規約どおり）

### PR Gate と Review Gate の違い

2 つの別々の gate が存在する。混同しない:

| Gate | 目的 | bypass 方法 |
| --- | --- | --- |
| Review Gate (`block-repeated-codex-review.sh`) | Codex レビューの 2 回目以降を防ぐ | `~/.claude/review-gate/.codex-review-done-$KEY` 削除（ユーザー指示要） |
| PR Gate (`block-pr-without-codex-review.sh`) | `gh pr create` 前に Codex レビュー未実施を防ぐ | `~/.claude/hooks/codex-review-bypass.sh "理由"` を実行（ログ記録、ユーザー指示要）。quota 切れだけは `--quota "<要旨>"` で Claude が自動記録してよい（ログに `quota-skip:` 接頭辞で残る） |

**`$KEY` の算出**: git リポジトリのルートパスと現在のブランチ名から算出する（レビューサイクル＝repo + branch 単位。別ブランチの過去レビューが新しいブランチの初回レビューをブロックしないため）。hook 内部（`hooks/lib/review-gate.sh`）で算出されるため、ユーザーが手動でパスを構築する場合は `KEY=$(printf '%s\n%s\n' "$(git rev-parse --show-toplevel)" "$(git rev-parse --abbrev-ref HEAD)" | shasum | cut -d' ' -f1)` で再現できる。

done flag は記録時の HEAD を 2 行目に保持する。同名ブランチを削除→再作成した場合、記録済み HEAD が現在の履歴の祖先でなくなる（stale）ため `block-repeated-codex-review.sh` が自動的に flag を削除して初回レビューとして通す。レビュー後にコミットを積んだだけ（同一サイクルの継続）は記録済み HEAD が依然祖先なので deny を維持する。

PR Gate も同じ祖先判定を使う。gate flag / Core Workflow の review evidence に記録された「レビューした commit」が現在の HEAD の祖先なら、レビュー後に積んだ修正 commit を含めてレビュー済みとみなして allow する（`LOCAL_REVIEW_CURRENT` = 同一 commit、`LOCAL_REVIEW_ANCESTOR` = 修正 commit あり、`LOCAL_REVIEW_SKIPPED` = quota SKIP）。完全一致を要求すると「指摘を全件修正して再レビューはしない」という本 policy の標準経路で PR 作成が必ず deny されるため、等価ではなく祖先関係で判定する。祖先でない（ブランチ作り直し・別履歴）場合だけ `REVIEW_STALE` で deny する。

### 禁止事項

- 修正 → 再レビュー、の自動ループ（修正は全件やるが、再レビューはユーザーの明示指示のみ）
- 「すべて対応した体」で push / PR を作る（P3 / scope 外の残件は PR 本文に明記する）
- quota 切れ以外の理由で bypass をユーザー確認なしに記録する
- quota SKIP を記録したのに PR 本文に書かない、または「レビュー済み」と書く
- 「3 回までならループしていい」という誤解（閾値は 1 回）

### 関連ファイル

- `skills/pre-review-check/SKILL.md`: レビュー前の自己チェックと、必要時の補助チェック
- `hooks/*`: Codex レビューの 2 回目以降を機械的にブロックする PreToolUse hook
