---
name: dead-code-audit
description: コードベース全体の未使用コード・孤立設定・陳腐化テストを安全に探索・削除し、真のバグ修正と決定論的チェックの通過を確認する。
user-invocable: true
argument-hint: "[optional focus]"
compatibility: codex opencode pi omp claude
---

# Dead Code Audit

コードベース全体を深層探索し、使われなくなったレガシーコード、孤立した設定・ドキュメント・フラグメント、不要なテストを安全に削除し、真のバグを修正する自律ワークフロー。

テストの価値判断や保持基準は `test-audit` skill の基準（Junk patterns / Retention bar）に従う。

## 原則

1. **サブエージェントによる並行探索（Parallel Recon）**:
   大規模コードベースでは、テスト層（低価値テスト・重複・壊れたテスト）と本番コード／SSOT設定層（孤立ファイル・未使用シンボル・不要設定）に探索軸を分割し、Read-only サブエージェントを活用して探索を並行化する。
2. **削除前の陳腐化証明（Prove Obsolete Before Removal）**:
   「参照が見当たらない」という理由だけで安易に削除しない。静的検索（`rg`）、リポジトリ設定（targets, manifest, router）、動的ディスパッチの有無を検証し、真に obsolete である証拠（呼び出し元ゼロ・非参照）を提示する。
3. **真のバグ修正（Fix Genuine Bugs, Don't Hide Failures）**:
   テストが失敗しているとき、テストを削除したりアサーションを緩めて無理やり Green に偽装（hiding failures）することを厳禁とする。仕様変更に伴い真に不要になったテストのみ削除し、実装・設定・環境の不整合が原因の真のバグは修正する。
4. **有用なカバレッジと公開契約の維持（Preserve Meaningful Coverage）**:
   `test-audit` の Retention bar（公開 API・セキュリティ・アーキテクチャ・回帰防止）を満たすテスト・コードは一切消さない。削除対象は Junk patterns に該当するもの、および削除されたコードに伴う不要テストに限定する。
5. **決定論的チェックの全通過（Preserve Deterministic Checks）**:
   変更後はプロジェクト必須のチェック（lint, typecheck, target drift check, test suite）を全件パスさせる。直せない本質的課題は推測で触らず残存ブロッカーとして報告する。

## ワークフロー

### Phase 1: Recon & 探索軸の分割
- リポジトリの検証コマンド、テスト構成、パッケージ境界、SSOT レイアウトを把握する。
- 探索軸を独立した関心事に分割する（例: サブエージェント1「テストコード監査・重複／壊れたテスト特定」、サブエージェント2「本番コード・設定・SSOTの孤立／デッドコード特定」）。

### Phase 2: 並行監査（Subagent / Focused Search）
- 各サブエージェントは Read-only で調査を行う。
- 候補ごとに次を記録・報告する：
  - 対象ファイルパスとシンボル／テスト名
  - 陳腐化の証明（呼び出し元ゼロ、静的参照なし、外部契約なし）
  - 削除リスクと影響範囲

### Phase 3: 親による検証・選別（Vetting & Confirmation）
- サブエージェントの過剰報告や False Positive（動的ディスパッチ、`__all__`、他ターゲットの設定、外部契約）を親が直接ファイルを開いて除外する。
- ユーザーに「削除候補」「バグ修正候補」「保持理由」を提示し、合意を形成する。

### Phase 4: 適用・バグ修正・全件検証
- 孤立コード・不要テストの安全な削除と、本質的バグの修正を適用する。
- プロジェクト標準の検証コマンド群（lint, test, build, distribute check）を実行し、全 Green を確認する。

### Phase 5: メトリクス付き報告
- 削除したコード行数 / テスト数
- 修正した真のバグと原因
- 保持した重要な契約
- 残存ブロッカー（Remaining Blockers）
