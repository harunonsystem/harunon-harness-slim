# ADR

確定済みの設計判断を 1 ファイル 1 決定で記録する場所（判断基準: 後戻りコストが大きい・文脈なしでは不可解・実在したトレードオフの選択、の 3 条件を満たすもの）。

## 規約

- `001-` 形式で連番。Status は見出しに inline で書く（`## Status: Accepted`）
- 覆した決定は消さず `Superseded` にして残す。追記修正は `Accepted (Amended YYYY-MM-DD)` と本文追記で行う
- ADR は改番・移動・旧本文の削除をしない。調査ログや実験結果は `docs/experiments/`、実装計画は `docs/plans/` に分ける

## 索引

| # | Title | Status |
| --- | --- | --- |
| 001 | 全ツールへの配布はファイルコピー方式 | Accepted |
| 002 | core / extras の分離基準 | Accepted |
| 003 | ターゲット定義の distribute スキーマ（patches は廃止） | Accepted (Amended 2026-09-03) |
| 004 | OpenCode の rules/skills 配布方式 | Superseded (2026-07-26; bridge self-contained 2026-07-27) |
| 005 | /copy-skills-to-codex を廃止し /sync-settings に統合 | Accepted |
| 006 | Agent Quality Pipeline（gVisor なし） | Accepted |
| 007 | Headroom を導入せず rtk を維持 | Accepted — rtk 一本維持で決着 (2026-07-26) |
| 008 | hash-bound distribution ledger for deletion propagation | Accepted (Amended 2026-09-03) |
| 009 | 開発 rigor profile による hook / policy の分類 | Accepted |
| 010 | Codex / pi / omp の Sol・Luna ルーティング | Accepted (Amended 2026-09-03) |
| 011 | 外部 skill は upstream を正本にし、SSOT から vendored コピーを退役させる | Accepted |
| 012 | Harness を worker orchestration の coordinator にする | Accepted |
| 013 | Model/provider に依存しない agent 境界と target socket | Accepted |
