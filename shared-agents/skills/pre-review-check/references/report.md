# 報告形式

正常時は短く報告し、問題や確認不可がある場合だけ根拠を詳しく書く。

```text
Pre-review check: PASSED | BLOCKED | INCOMPLETE
対象: local / staged / commit / branch / PR、base/head、変更ファイル数
Findings: PRC-001 [new|persists|resolved] [critical|major|minor] file:line — 影響と修正案
カテゴリ: PASS=2,8,10 / FAIL=6 / N/A=1,3,4,5,7,9,11 / 確認不可=なし
検証: 実行コマンドと結果、補助チェックの実行またはスキップ理由
未確認: 不足資料・実行不可の検査と理由
次: 未解決問題の修正、未確認の解消、または外部レビューへ進める旨
```

11カテゴリすべてを結果のどれかに含める。N/Aは対象外の理由をまとめて付記する。
Findingがなければ「なし」と書く。カテゴリのPASSにFinding IDは不要。
criticalは本番障害・セキュリティ・データ不整合、majorはバグ・適用規約違反、minorは非ブロッキングの改善提案。
BLOCKEDと確認不可が同時にある場合、判定はBLOCKEDとして未確認も併記する。
未実行のコマンド・利用不可のサービスを「確認済み」と書かない。
