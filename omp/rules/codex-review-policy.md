---
description: 公開前のセルフチェックと、明示依頼された外部レビューの運用。push・PR 前、および /codex:review 実施前に読む。
paths:
  - "**/codex-review-policy.md"
---

## 公開前チェックと外部レビュー

### 標準フロー

push・PR の前に `pre-review-check` を必ず実施する。Markdown のみの変更も対象とし、不要な検査は理由付きで N/A にする。独立した外部レビューはユーザーが明示的に依頼した場合だけ実行する。

1. ブランチ全体の diff と受入条件を確認し、必要なテスト・lint・build を実行する。
2. critical / major を修正して再検証する。`BLOCKED` / `INCOMPLETE` のまま公開しない。minor・scope 外の残件は PR 本文に明記する。
3. 完全な `PASSED` 報告を実ファイルに保存する。base/head、Finding、検証結果、未実施の任意チェックと理由を含める。
4. `run-change` の `attach-review --provider self-check` で現 HEAD の報告を記録し、`advance accepted` 後に `authorize pr.create` を通す。
5. commit・push・PR はユーザーの承認範囲で行う。明示された公開依頼を再確認しない。

進行中の Core Workflow がなければ、実装・検証・commit 済みのブランチで `start <task-id> --publish-only` を使う。legacy gate flag の作成や bypass でセルフチェックを代替しない。

自己チェックは独立レビューではない。ローカル証跡は `audit-only` であり、PR 公開時の作業漏れ防止に限る。kernel は報告の存在・HEAD・phase を検証するが、本文の合格判定は agent が確認する。merge には引き続き外部の required status check と branch rules が必要。

### 外部レビューを明示依頼された場合

- 実行は 1 回まで。自動の修正→再レビューループを作らない。再レビューはユーザーの明示指示がある場合だけ行う。
- If the active model provider is `openai-codex`, use an independent runtime-native reviewer or explicit review surface and do not invoke `codex-companion.mjs`. Codex は configured `review_model` の `reviewer`、他の runtime は利用可能な独立 reviewer を使う。利用不可なら未実施と報告し、依頼された外部レビューを自己チェックで置き換えない。
- active provider が `openai-codex` 以外のときだけ `/codex:review` の companion を使う。companion と `codex app-server` は sandbox 外で実行する。native background 実行があれば完了通知を待ち、shell session を poll しない。
- reviewer の全出力を保存して実 provider 名で `attach-review` する。P0 / P1 / P2 は同じブランチで全件修正し、必要な検証後に `advance findings_fixed` で進める。P0 が直せない場合は公開を止める。P3 / scope 外は PR 本文に残す。
- 修正 commit は今回の差分だけを stage する。レビューの依頼自体は commit の承認ではない。既存の決定や scope と衝突する修正だけユーザーに確認する。
- quota / credit 切れで出力が返らない場合は再試行せず、必須のセルフチェックを通したうえで `skip-review` に実際の理由を記録する。PR 本文に外部レビュー未実施を明記し、レビュー済みと書かない。
- 接続・認証・crash は quota skip ではない。明示依頼を満たせないと報告し、依頼の変更または例外の承認を待つ。

### 既存 gate との関係

`block-pr-without-codex-review.sh` は active な Core Workflow の PR 公開判定を kernel に委譲する。自己チェックの証跡も `local-review` として扱い、現 HEAD またはその祖先の記録を受け付ける。この証跡では merge は承認されない。今回の公開後に別履歴を作った場合は stale として拒否される。

旧 runtime の review-router は Markdown・生成物・通常コード・大きな diff を分類し、workflow 外では legacy flag を参照する。この互換経路が allow しても標準フローのセルフチェックは免除されない。`block-commit-without-difit.sh` の大きな diff 向け gate も維持する。

`block-repeated-codex-review.sh` は外部レビューの 2 回目以降を防ぐ。active workflow の再実行はユーザー承認後の `approve-review`、legacy 経路の done flag 削除もユーザーの明示指示が必要。flag は repo + branch ごとに記録され、レビューした HEAD が現履歴の祖先でなければ stale になる。

### 禁止事項

- 未実施の検査を合格・レビュー済みと記録する。
- quota 以外の失敗を quota skip に偽装する。
- セルフチェックを省いて legacy bypass または writable なローカル状態で公開・merge を承認する。
- 無関係な未 commit 変更を上書きする、または指摘修正に巻き込む。

判定と Finding ID は `rules/review-policy.md`、報告形式は `skills/pre-review-check/references/report.md`、証跡の操作は `skills/run-change/SKILL.md` を参照する。
