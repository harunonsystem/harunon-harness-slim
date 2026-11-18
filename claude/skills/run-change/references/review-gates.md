# レビューゲートとエビデンス結合

## 1. Pre-review check と Self-check の添付

完成・push・PR 作成の前に、ブランチ全体の差分に対して `pre-review-check` を実行する。
`critical` および `major` な指摘を解消し、必要な決定論的チェックを実行する。`PASSED` レポートを一時アーティファクトとして保存する。

Self-check レポートを添付する:

```bash
python3 <skill-dir>/scripts/harness.py attach-review \
  --revision <revision> --provider self-check --subject-sha "$(git rev-parse HEAD)" \
  --artifact <self-check-report-file>
```

カーネルは、アーティファクトの欠落、古い HEAD、無効なフェーズ、未承認の 2 回目独立レビューを拒否する。
免除対象でない変更では、Self-check の添付によってフェーズは `review` に留まる。

## 2. 独立 AI レビューの実行と添付

コード、スクリプト、フック、設定変更には 1 回の独立 AI レビューを実行する。
`rules/codex-review-policy.md` の免除規定（Markdown/テキスト等）を守る。

- Codex: アクティブランタイムの reviewer を使用。
- その他プロバイダ: codex-companion 経由で `/codex:review` を実行。

完全なレビューア出力を保存し、実際のプロバイダを指定して添付する:

```bash
python3 <skill-dir>/scripts/harness.py attach-review \
  --revision <revision> --provider <actual-provider> --subject-sha "$(git rev-parse HEAD)" \
  --artifact <independent-review-output-file>
```

指摘事項が提示されたら、ブランチ上で P0 / P1 / P2 をすべて修正し、`advance findings_fixed` を記録する（2 回目のレビューは不要）。
P3 およびスコープ外の指摘は PR 本文の「残件」に記載する。

## 3. レビューの Skip と承認

レビューアがクォータ・クレジット枯渇で応答しない場合のみ、Self-check 通過後にスキップを記録する（接続・認証・crashはquotaとみなさず、下の明示例外を確認する）:

```bash
python3 <skill-dir>/scripts/harness.py skip-review --revision <revision> --provider <provider> --reason "<reviewer error summary>"
```

2 回目のレビューを実行するにはユーザーの明示承認が必要:

```bash
python3 <skill-dir>/scripts/harness.py approve-review --revision <revision> --reason "<user-approved reason>"
```

## 4. 非quota障害への明示的な例外

接続・認証・crashで独立reviewerの出力を取得できず、そのレビューを省略することを本人が明示承認した場合だけ、最終checkoutのself-checkと必須検証後に記録する。通常の「進めて」「PRを出して」や他taskの承認から例外を推定しない。承認がなければ該当作業を停止する。

実際の承認文と対象を、checkout外のJSONファイルに保存する。`subjectSha`と`inputHash`は承認対象と一致する成功済み必須検証receiptの値、`worktreeRoot`はcanonicalな絶対パス。providerとfailureKindも承認された障害に限定する。

```json
{
  "reason": "<このレビュー省略への実際の本人承認文>",
  "taskId": "<現在のtask ID>",
  "worktreeRoot": "<canonical absolute worktree path>",
  "subjectSha": "<approved HEAD>",
  "inputHash": "<approved verification receipt inputHash>",
  "provider": "<failed reviewer provider>",
  "failureKind": "connection"
}
```

`failureKind`は`connection` / `auth` / `crash`だけ。障害の事実と本人承認を分けて記録する:

```bash
python3 <skill-dir>/scripts/harness.py skip-review --revision <revision> --provider <provider> --reason "<actual reviewer failure>" --user-approval <absolute-approval.json>
```

kernelはtask・worktree・HEAD・入力hash・providerの一致と現HEADのself-checkを検査する。HEADだけでなく未commit入力が変わっても例外を再利用しない。PR本文には外部レビュー未実施と明示し、レビュー済みと書かない。これは`audit-only`の例外記録であり、kernelが本人発言の真正性を検証した証明ではない。呼出し側は実際の本人承認を確認し、native/platformの拒否・公開承認・会社の独立承認・secret検査・必須検証を代替しない。

OpenCodeのnative `harness_workflow` では `operation: "skip_review"` に同じオブジェクトを `userApproval` として渡す。CLI用ファイル名や単なる承認文字列は渡さない。kernelの同じscope検査を通す。

### 変更で例外が失効した場合

`publish`でHEADや入力が変わったら、旧例外を使わず、同じtaskで必須検証と現HEADのself-checkを更新する。`attach-review --provider self-check`で`decide`へ進み、`advance fix_selected`で`review`へ戻る。旧例外は監査履歴として残る。

復旧したreviewerの初回出力を`attach-review`するか、新しい対象範囲について本人の明示承認を得て、新しい承認JSONを`skip-review --user-approval`へ渡す。旧承認JSONや通常の「進めて」を新しい例外の承認として流用しない。既に実レビューを行ったtaskで再レビューが必要なら、従来どおり本人の明示依頼・承認と`approve-review`を必要とする。taskの置換や状態ファイルの直接編集はしない。
