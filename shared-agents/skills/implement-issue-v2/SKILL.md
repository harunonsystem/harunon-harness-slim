---
name: implement-issue-v2
description: /implement-issue-v2 または v2 での比較試行を明示されたときに使う Issue 実装フロー。通常の issue 実装は implement-issue を使う。
---

# implement-issue-v2

Issue と完了条件から必要な工程を選び、承認された範囲を最後まで進める。pstack の導入は不要。ユーザーに Skill の順番や agent の割当を指定させない。

## 入口を解決する

`$ARGUMENTS` は v1 と同じ PRD、Linear URL / ID、GitHub issue URL、直接説明。指定 branch と公開承認を保持する。例: `/implement-issue-v2 ABC-123 feature/abc-123-fix-name`。

未解決の準備だけ [v1](../implement-issue/SKILL.md) の該当節を参照する。設定・取得は「設定」「Phase 1」、変更用 worktree は「Phase 2」、変更フローへの接続は「Phase 3」。設定は v1 ディレクトリの `config.yml`、なければ [config.example.yml](../implement-issue/config.example.yml) を使う。branch / base / PR template も v1 と適用される repo・runtime 規約に従う。

同じ task の再開は、既存の repo・worktree・受入条件と現在の state を使う。準備が解決済みなら v1 の読み直しも省く。新しい入力や矛盾がない情報を取り直さない。別 task の state を上書きしない。

## 必要な工程を選ぶ

目的・受入条件・制約を確認し、関連する入口・実装・テストを読む。各受入条件に確認方法を対応させ、次の経路を選ぶ。工程一覧の承認待ちは挟まない。

| 入力・観測 | 進め方 |
| --- | --- |
| 調査だけ | 読み取り専用で根拠・結論・不明点を返して終了。worktree、変更 state、テスト追加、公開操作は行わない |
| 局所的で既存パターンが使える変更 | 親が実装して関連検証へ。設計比較・分担は省く |
| バグ・原因不明 | 修正前に最小再現を実行し、関連経路を追って原因を特定。修正後に同じ再現を実行。再現不能は未検証と明示。テスト追加・変更時は `test-audit` を適用 |
| 共有処理・公開契約に影響 | 呼び出し元・型・設定・関連テスト等を検索し、互換性と変更範囲を確定して実装 |

複数条件に当たるなら必要な工程を組み合わせる。局所的なバグでも修正前後の再現は省かない。新しい影響や不確実性が見つかったときだけ工程を追加する。

現仕様の理由が判断に必要なときだけ git log / blame と関連 Issue・ADR・資料を調べ、記録と推測を分ける。実質的に異なる解法が残るときだけ `derive-optimal-solution` を使う。既存情報で解決できず正しさやスコープを左右するユーザー判断だけ確認し、依存しない作業は進める。

## 実行して確かめる

変更の lifecycle・gate・公開は [run-change](../run-change/SKILL.md) に従う。状態や承認を別管理せず、既存 hooks / CI を維持する。調査限定ではこの変更フローを開始しない。

独立した分担の利益があるときだけ runtime-native の subagent を使う。範囲・受入条件・根拠・検証コマンドを渡す。複数 agent の編集は別 worktree に隔離し、できなければ逐次実行する。親は報告だけで合否を決めず、成果物と統合後の diff・検証結果を確認する。

受入条件の確認と repo 必須チェックを実行する。親が base からの全 diff と未 commit / untracked の成果物を読み、条件充足、配線・互換性、未検証経路、依頼外変更を確認する。公開前はこの確認を `pre-review-check` にまとめ、独立レビューは明示依頼時だけ行う。修正後は影響する検証を再実行し、以前の結果を流用しない。

承認済みの公開は再確認せず進める。未承認なら必要な実装・検証を終えてから公開前に確認する。PR の承認を merge に広げない。変更・検証・未確認事項と、作成した場合の PR URL を報告する。

## 比較記録

開始時の task・規模・runtime / model・base と、追加指示・手戻り・agent 呼び出しの発生を作業 context に残す。終了時にだけ [比較方法](references/comparison.md) を読み、既存の評価メモかこのチャットへ記録する。未観測値は推測せず、Issue / PR へ評価ログを自動投稿しない。

この Skill 自体の改訂時だけ [固定評価シナリオ](references/evaluation.md) を使う。
