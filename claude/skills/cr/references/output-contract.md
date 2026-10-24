# コードレビュー Output Contract と Finding ルール

## Output Contract

対象・判定・risk・必要な根拠を短く出す。正常項目の表や空の Finding 表は作らない。

```text
Code review: APPROVE | REJECT | INCOMPLETE
Risk: low | medium | high — 分類根拠
対象: local / staged / commit / branch / PR、比較ref/SHA、変更ファイル数
Findings: ID [status] [severity] file:line — 影響・根拠・再現/契約・修正案（なければ「なし」）
検証: blocking candidate の再検証と、実行した検査の結果
未確認: 不足資料・未実行の必要な検証と理由（なければ省略）
Human gate: repo規則で必要な場合だけ記載。AI review を人間承認済みとは書かない
次: 必要な修正・確認、またはレビュー完了
```

blocking / warning / out-of-scope を混同せず、指摘がある区分だけ示す。
対象外の変更はレビュー範囲の説明にまとめ、問題を確認していなければfinding件数に数えない。
必要な差分・根拠を確認できず、確定したブロッキング問題もない場合は `INCOMPLETE`。
既知の問題があれば `REJECT` とし未確認も併記する。検査を実行していなければ成功と書かない。

## Finding ID のルール

- 全 blocking 指摘に `finding_id` を付与。ID は担当 subagent の prefix 付き（`RVW-001`, `ARCH-001`, `SEC-001`）を統合後も維持する。複数観点の同一指摘を統合した場合は根拠が強い方の ID を残し、統合元 ID を Issue 欄に併記する
- 再レビュー時は前回の finding_id を引き継ぎ、ステータスを更新:
  - `new`: 今回新規検出
  - `persists`: 前回指摘から未修正（エビデンス必須）
  - `resolved`: 前回指摘が修正済み
  - `false_positive`: 再検証で問題なしと判明
  - `overreach`: 技術的には正しいがタスクスコープを超過
- それ以外の運用ルール（finding_id なし指摘の扱い、ID の意味不変性等）は `rules/review-policy.md`「Finding ID 追跡」節に従う

## Severity レベル

| Severity | 定義 |
| --- | --- |
| critical | セキュリティ問題、データ不整合、本番障害リスク |
| major | バグ、REJECT基準（review-policy.md）への違反 |
| minor | 改善推奨だがブロッキングではない |
| info | 情報提供のみ |
