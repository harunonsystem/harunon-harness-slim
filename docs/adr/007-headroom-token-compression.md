# ADR-007: Headroom (API Proxy Token Compression) の評価と採否

## Status: Accepted — rtk 一本維持で決着（2026-07-26）

## 決着（2026-07-26）

再検討条件のうち「1M コンテキスト問題（Issue #1158）の解決」は成立した（closed 確認済み、`plans/018-headroom-recheck-ops.md`）。その上で**不採用のまま決着**とする:

- 不採用理由の主因（proxy 常駐が単一障害点、Bedrock 非対応）は未解消
- 導入から 1 ヶ月以上、headroom を実際に使う場面がなかった（`packages/core/CLAUDE.md` は 2026-07-11 に常駐参照を除外済み）
- 以後の再検討は「proxy 不要の圧縮モード提供」のみをトリガーとし、`/harness-update` での issue 定期確認は打ち切る

## Context

Claude Code のトークン消費を削減する手段として、既存の rtk（Rust Token Killer）に加え headroom（API proxy 方式）を評価した。

rtk は PreToolUse hook でコマンドを書き換え、shell 出力を 60-90% 圧縮する。headroom は `ANTHROPIC_BASE_URL` を localhost proxy に向け、API リクエスト/レスポンス全体を圧縮する。レイヤーが異なるため併用可能。

SNS 上で「headroom は rtk の上位互換」「可逆圧縮で品質劣化なし」との評価があり、移行を検討した。

## 調査結果（2026-06-24）

| 観点 | 結論 |
| --- | --- |
| 可逆圧縮 | CCR（Compress-Cache-Retrieve）方式。LLM が `headroom_retrieve` MCP ツールを呼ぶと原本取得可能。人間が直接見るには不向き |
| rtk 内包 | しない。headroom は API レベル圧縮、rtk はコマンド rewrite。補完関係 |
| Bedrock 共存 | 未対応。Bedrock SDK は SigV4 署名で直接 AWS に送るため `ANTHROPIC_BASE_URL=localhost` が効かない（Issue #510） |
| 1M コンテキスト | proxy 経由だとベータヘッダーが落ちて 200k に制限される（Issue #1158）。`[1m]` モデル指定で回避可能 |
| レイテンシ | 1-5ms/req（軽微） |
| 安定性 | proxy 停止時に API 全停止。ConnectionRefused で 4 分以上リトライ後に死亡する事象を確認済み |
| 実測節約 | rtk 1.33B トークン + headroom 189M トークン（Andrew Patterson 氏の 1 ヶ月実測） |

## Decision

**現時点では rtk 一本を維持。headroom は将来の選択肢として文書化のみ行う。**

理由:
1. proxy 常駐が単一障害点になる（体験済み）
2. Bedrock 構成で使えない
3. rtk の上位互換ではなく補完関係であり、rtk を置き換えられない
4. headroom 追加分の節約（16-59%）は proxy 運用コストに見合わない

再検討条件:
- Bedrock 対応（Issue #510）が実装された
- 1M コンテキスト問題（Issue #1158）が根本解決された
- proxy 不要の圧縮モード（hook ベース等）が提供された

確認手順: 対象 issue（いずれも `headroomlabs-ai/headroom`。旧 `chopratejas/headroom` は同リポジトリへリダイレクト）の state を以下で確認する。

```bash
gh issue view 510 --repo headroomlabs-ai/headroom --json state
gh issue view 1158 --repo headroomlabs-ai/headroom --json state
```

確認は `/harness-update` 実行時に行っていた。この定期確認は上記「決着（2026-07-26）」で打ち切り済みで、`/harness-update` 自体も 2026-08-28 に `/sync-settings` へ集約して廃止した。

## Consequences

- `packages/core/HEADROOM.md` を opt-in ドキュメントとして配布（`packages/targets/claude/config.json`）
- `packages/core/CLAUDE.md` の Token Optimization 節に `@HEADROOM.md` 参照を追加
- SSOT（`packages/core/settings.json`）に `ANTHROPIC_BASE_URL` を入れない（テストで検証）
- rtk-rewrite hook と関連テストは維持

## References

- [headroom GitHub](https://github.com/chopratejas/headroom)
- [Issue #1158: 1M context window 制限](https://github.com/headroomlabs-ai/headroom/issues/1158)
- [Issue #510: Bedrock provider-agnostic proxy](https://github.com/chopratejas/headroom/issues/510)
- [Token Compression for Claude Code with RTK + Headroom（実測データ）](https://andrewpatterson.dev/posts/token-savings-rtk-headroom/)

## 追補（2026-08-30）: 現行の配布状態

Consequences にある `HEADROOM.md` の配布と `CLAUDE.md` からの参照は歴史的記述であり、現在は適用しない。`packages/core/HEADROOM.md` は存在せず、`ANTHROPIC_BASE_URL` も SSOT に設定しない。`/harness-update` の定期確認も廃止済みで、現行の決定は「rtk 一本を維持し、proxy 不要の圧縮方式が出た場合だけ手動で再評価する」である。
