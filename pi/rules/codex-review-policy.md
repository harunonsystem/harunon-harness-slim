---
description: 公開前のセルフチェックと、明示依頼された外部レビューの運用。push・PR 前、および /codex:review 実施前に読む。
paths:
  - "**/codex-review-policy.md"
---

## 公開前チェックと外部レビュー

### 標準フロー

完了報告・push・PR の前に `pre-review-check` を必ず実施する。Markdown のみの変更も対象とし、不要な検査は理由付きで N/A にする。独立した外部レビューはユーザーが明示的に依頼した場合だけ実行する。

1. ブランチ全体の diff と受入条件を確認し、必要なテスト・lint・build を実行する。
2. critical / major を修正して再検証する。`BLOCKED` / `INCOMPLETE` のまま公開しない。minor・scope 外の残件は PR 本文に明記する。
3. 完全な `PASSED` 報告を実ファイルに保存する。base/head、Finding、検証結果、未実施の任意チェックと理由を含める。
4. `run-change` のkernel `verify`で必須検証を記録し、`attach-review --provider self-check`で現HEADの報告を記録する。`advance accepted`後、完了だけなら`complete`、PR作成なら`authorize pr.create`を通す。変更・commit後は必須検証を再実行する。
5. commit・push・PR はユーザーの承認範囲で行う。明示された公開依頼を再確認しない。

進行中のCore Workflowがなければ、native作業済みのworktreeで`start <task-id> --publish-only`を使う。未commitでもよく、この入口はcommitや公開を許可しない。legacy gate flagの作成やbypassでセルフチェックを代替しない。

自己チェックは独立レビューではない。ローカル証跡は `audit-only` であり、PR 公開時の作業漏れ防止に限る。kernel は報告の存在・HEAD・phase を検証するが、本文の合格判定は agent が確認する。merge には引き続き外部の required status check と branch rules が必要。

pstack の `architect` / `interrogate` 等が使う runtime 内の設計批評・レビュー panel は承認済み実装の一部として実行できる。以下の外部レビュー承認・再実行制限は別途起動する外部 review service に適用する。panel の結果だけで必須セルフチェック・公開承認・merge 承認を代替しない。

### 外部レビューを明示依頼された場合

- 実行は 1 回まで。自動の修正→再レビューループを作らない。再レビューはユーザーの明示指示がある場合だけ行う。
- If the active model provider is `openai-codex`, use an independent runtime-native reviewer or explicit review surface and do not invoke `codex-companion.mjs`. Codex は configured `review_model` の `reviewer`、他の runtime は利用可能な独立 reviewer を使う。利用不可なら未実施と報告し、依頼された外部レビューを自己チェックで置き換えない。
- active provider が `openai-codex` 以外のときだけ `/codex:review` の companion を使う。companion と `codex app-server` は sandbox 外で実行する。native background 実行があれば完了通知を待ち、shell session を poll しない。
- reviewer の全出力を保存して実 provider 名で `attach-review` する。P0 / P1 / P2 は同じブランチで全件修正し、必要な検証後に `advance findings_fixed` で進める。P0 が直せない場合は公開を止める。P3 / scope 外は PR 本文に残す。
- 修正 commit は今回の差分だけを stage する。レビューの依頼自体は commit の承認ではない。既存の決定や scope と衝突する修正だけユーザーに確認する。
- quota / credit 切れで出力が返らない場合は再試行せず、必須のセルフチェックを通したうえで `skip-review` に実際の理由を記録する。PR 本文に外部レビュー未実施を明記し、レビュー済みと書かない。
- 接続・認証・crash は quota skip ではない。明示依頼を満たせないと報告し、依頼の変更または例外の承認を待つ。

### 既存 gate との関係

v2の`harness-publication-gate.sh`とnative adapterは公開判定をkernelに委譲する。タスク未開始・完了済みでも検証を迂回しない。自己チェックは`local-review`として現HEADまたは祖先の記録を受け付けるが、必須検証は常に現在のcheckoutに一致させる。この証跡ではmergeは承認されない。

旧runtimeの`block-pr-without-codex-review.sh`とreview-routerはlegacy経路として残るが、v2公開gateの代替ではない。旧経路がallowしても必須検証・セルフチェックは免除されない。`block-commit-without-difit.sh`の大きなdiff向けgateも維持する。

`block-repeated-codex-review.sh` は外部レビューの 2 回目以降を防ぐ。active workflow の再実行はユーザー承認後の `approve-review`、legacy 経路の done flag 削除もユーザーの明示指示が必要。flag は repo + branch ごとに記録され、レビューした HEAD が現履歴の祖先でなければ stale になる。

### 禁止事項

- 未実施の検査を合格・レビュー済みと記録する。
- quota 以外の失敗を quota skip に偽装する。
- セルフチェックを省いて legacy bypass または writable なローカル状態で公開・merge を承認する。
- 無関係な未 commit 変更を上書きする、または指摘修正に巻き込む。

判定と Finding ID は `rules/review-policy.md`、報告形式は `skills/pre-review-check/references/report.md`、証跡の操作は `skills/run-change/SKILL.md` を参照する。
