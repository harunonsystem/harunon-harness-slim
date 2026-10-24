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

レビューアがクォータ・クレジット枯渇で応答しない場合のみ、Self-check 通過後にスキップを記録する（接続エラー・認証エラーはスキップとみなさずユーザーに確認する）:

```bash
python3 <skill-dir>/scripts/harness.py skip-review --revision <revision> --provider <provider> --reason "<reviewer error summary>"
```

2 回目のレビューを実行するにはユーザーの明示承認が必要:

```bash
python3 <skill-dir>/scripts/harness.py approve-review --revision <revision> --reason "<user-approved reason>"
```
