# ADR-006: Agent Quality Pipeline（gVisor なし）

## Status: Accepted

## Context

Anthropic の C/C++ vulnerability discovery harness は、build → recon → find → grade → judge → report → patch というパイプラインと gVisor サンドボックスで「実行結果の標準化」「独立 grading」「再現可能な artifact」を実現している。

harunon-harness は設定同期・スキル管理が主目的であり、脆弱性探索 harness をそのまま移植するのはドメイン不一致。ただし以下の概念は転用できる:

- **Executor / Grader 分離**: 改善提案を別エージェントで検証し、自己評価バイアスを減らす
- **Artifact 標準化**: finding_id, manifest.jsonl 等で結果を機械可読にする
- **メタ検証**: SSOT（CLAUDE.md, commands.md, targets config）の整合をスクリプトで検出

一方、gVisor 等の OS レベルサンドボックスは harness 開発・設定同期の文脈では過剰。既存の worktree / subagent / empirical-prompt-tuning で十分な isolation が取れる。

## Decision

1. **Phase 1（本 ADR）**: gVisor なしで quality pipeline の設計方針を文書化
2. **Phase 2**: `scripts/validate-harness.py` でメタ整合チェックを機械化
   - CLAUDE.md ↔ correction-lessons.md の節カウント
   - targets config の distribute source 実在
   - commands.md ↔ skills/ の対応（警告）
3. **Phase 3以降**: empirical-prompt-tuning / insights / sync-settings に artifact ベースの grading を段階追加

検証スクリプトは Python 標準ライブラリのみ（merge-settings.py と同様）。外部依存なし。

## Consequences

- CI / pre-commit に `python3 scripts/validate-harness.py` を追加可能
- insights スキルの Step 4.5 と validate-harness.py が同じチェックを共有（insights はログ分析 + メタ、validate-harness は決定論的メタのみ）
- commands.md に未記載の utility スキル（auto-trigger 等）は警告として残す。幽霊エントリ（commands あり skills なし）はより深刻
- gVisor 相当の isolation は求めない。subagent + scenario manifest で代替

## 追補（2026-07-02）: correction-lessons.md 節カウント検証の廃止

2026-06-22 に `rules/correction-lessons.md` は `rules/core-standards.md` へ統合され（コミット `d7d4589`）、Decision 節 2 の「CLAUDE.md ↔ correction-lessons.md の節カウント」検証は対象ファイルが無くなったため廃止された。`validate-harness.py` は該当チェックをファイル不在時にスキップする実装のまま残っていたため、実質的な no-op になっていた（Plan 001/002 で参照修正・スキップ実装の整理を実施）。

## 追補（2026-08-30）: 現行の quality pipeline

Phase 3 の `empirical-prompt-tuning` / `insights` / `sync-settings` への artifact grading は採用しなかった。現行の品質担保は `scripts/run-tests.py`、`scripts/validate-harness.py`、`shellcheck`、CI の決定論的チェックで構成する。上記 Phase 1〜3 と `insights` に関する記述は当時の検討履歴として残すが、現行実装の依存関係ではない。
