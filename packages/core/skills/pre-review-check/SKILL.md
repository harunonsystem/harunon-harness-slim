---
name: pre-review-check
description: '/codex:review 実行前の統合自己チェック。Codex が繰り返し指摘する観点と AI アンチパターンを 11 カテゴリで先回り検証し、/similarity-check・/ponytail-review・/simplify で仕上げてから 1 周で通す。「プレレビュー」「レビュー前チェック」「セルフチェック」などで起動。'
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - Agent
  - Skill
  - mcp__figma__get_screenshot
  - mcp__figma__get_design_context
---

# Pre-Review Check

`/codex:review` に投入する前に、Codex が過去に繰り返し指摘した観点と AI アンチパターンを自分で潰すためのスキル。
自己チェック（Phase 2-3）→ 重複・簡素化パス（Phase 4）まで回してから `/codex:review` に流すのが標準ルート。
レビュー自体はここでは実行しない: 手動レビューが欲しいときは `/cr`（Rails は内部で `/self-review` に委譲）、diff の目視は `/difit` を別途使う。

**Codex レビューは 1 回まで**（詳細: `rules/codex-review-policy.md`）。**1 周で通す**ことが前提。

## いつ使うか

- 実装完了後、`/codex:review` の直前
- PR 作成直前（hook が `gh pr create` をブロックする前に）
- `/implement-issue` / `/figma-implement` 系スキルの最終フェーズ（セルフレビューの一部として）

## 原則

- **silence is not success**: Codex が指摘しなかった観点も、このスキルでは主体的に探しに行く
- **Finding ID 付きで記録**: 見つかった issue は `PRC-<番号>` を付けて iteration 可能にする
- **grep で裏取り**: 断定前に必ずコマンドで確認する

## Iteration 追跡

**初回実行時**: 全 11 カテゴリを網羅的にチェックし、全問題を報告する。
**2 回目以降**: 前回 FAIL の finding_id の修正確認を優先する。N/A カテゴリは再チェック不要。

## 11 カテゴリのチェック項目

### 1. 関連 Linear Issue の合意事項

**狙い**: 親 / 兄弟 Issue で決まっている命名・URL 値・スコープを見落とさない。

| やること | コマンド例 |
| --- | --- |
| 着手 Issue を取得 | Linear MCP の `get_issue` で対象 Issue |
| 親 Issue を取得 | `parentId` があれば再帰的に取得 |
| 兄弟 Issue を列挙 | Linear MCP の `list_issues` で `parentId` 一致のもの |
| 各 Issue の URL 値 / 型名 / 合意事項をメモ | description 本文から抽出 |

**典型的な失敗**: 兄弟 Issue で合意済みの URL クエリ値（例: `payment_info`）を読まずに独自命名で実装 → Codex 指摘。

### 2. 既存ドメイン型・語彙との整合

**狙い**: 同じ概念に別名を付けて型を分岐させない。

- 新規型を追加する前に必ず grep して既存定義を確認する
- 命名パターン（kebab-case vs camelCase、接頭辞）も既存に合わせる
- 既存型が enum 値を持つ場合、すべての値を網羅するか確認する

**典型的な失敗**: 既存 `UserRoleType = 'admin' | 'member'` なのに新規実装で `'admin' | 'general'` と定義 → API が `member` を返すと表示崩れ。

### 3. 削除対象コンポーネントの機能棚卸し

**狙い**: 置換や削除で既存機能を落とさない（回帰防止）。

置換・削除する前に対象コンポーネントが提供する以下を列挙し、新実装にマップする:

- リンク / ボタン / モーダル / ドロップダウン
- 条件分岐による表示切替
- 外部機能への導線（他ページへの遷移）
- 認証チェックや権限分岐

**典型的な失敗**: 既存コンポーネントが持っていた所属編集リンクを削除してしまい、既存フローが使えなくなった。

### 4. Figma デザイン要素の逆引き

**狙い**: デザインに描かれている要素を取りこぼさない。

- Figma のスクショの各要素を箇条書きで書き出す（ヘッダー / バッジ / リンク / ボタン / 件数表示 / 空状態など）
- それぞれ実装にマップする。「見落としていた要素」がないか確認
- ラベルテキスト・アイコン・tooltip もすべて対象

**典型的な失敗**: 所属行の「編集」リンクが Figma に描いてあるのに実装で省略した。

### 5. UI コンポーネントの variant × type サポート

**狙い**: デザインシステムで定義されていない組み合わせを使わない。

- `Label` / `Button` / `Chip` 等を使う前に対応する `.module.scss` を開く
- 使う予定の `variant × type` の組み合わせが **すべてスタイル定義されているか**確認
- 定義がないなら別の組み合わせを選ぶか、デザインシステム側に追加する

**典型的な失敗**: `Label type="fillSoft" variant="primary"` と書いたが `.fillSoft` に `.primary` 定義がなく、素のラベル表示。

### 6. 未実装ボタンの扱い

**狙い**: no-op な onClick を残さない（UX 不具合）。

- バックエンド未実装で動かないボタンは **最初から `disabled` + `title` 属性** で書く
- onClick に `() => undefined` を書かない
- 「もっと見る」「保存」「送信」など動作が期待されるボタンは特に注意

**典型的な失敗**: 保存ボタン・「もっと見る」ボタンに空 onClick を付けて「クリックしても何も起きない UI」を出した。

### 7. ダミー / PII 風データの配置

**狙い**: prod バンドルに PII 風データを残さない。

- `src/mocks/handlers/` + `src/mocks/data/` に配置する
- `useFetch*` 側は実 API を叩く形にして、MSW 有効時のみモック応答を返す
- hook 本体や component 本体に直書きしない

**典型的な失敗**: hook 内にダミーデータを直書き → 本番バンドルに PII 風データが含まれる。

### 8. プロジェクト慣例のコード例準拠

**狙い**: プロジェクト固有の慣例（styling 方式・props 参照規約・デザイントークン）に揃える。

- プロジェクト固有 conventions（extras 側で配置）に従っているか確認する
- Error/Loading/Empty/Normal の 4 状態が実装されているか（→ カテゴリ 11 で詳細チェック）
- セマンティックトークンを使っているか（px値/カラーコード直書き禁止）
- props 参照規約（分割代入禁止等）に従っているか

**典型的な失敗**: `const { basicInfo } = props` と分割代入したが、プロジェクトの例は `props.basicInfo` 直接参照だった。

### 9. セキュリティ sink の混入

**狙い**: 注入・XSS・安全でないデシリアライズ・機密流出を push 前に潰す。判定基準は `rules/review-policy.md`「セキュリティ REJECT 基準」が SSOT、sink 詳細表は同ファイル経由で `skills/cr/references/security-sinks.md` を参照する。

- diff を grep して sink 詳細表の各 sink を洗う
- ヒットした各 sink で source→sink を追い、外部入力が未検証・未エスケープで到達しないか確認
- grep で出ない観点: 機密の log/例外メッセージ流出（except 分岐）、IDOR/認可バイパス、SSRF、path traversal、CI/CD トリガーの信頼境界
- 安全な根拠は該当行直前コメントに明記

**典型的な失敗**: ユーザー制御パスを `filepath.Clean` / 許可ディレクトリ検証なしで `open` に渡し path traversal を作る。

### 10. AI アンチパターン 11 カテゴリ

**狙い**: `rules/core-standards.md`「AI 生成コード検証」の全カテゴリを網羅する。詳細な判定基準は同ファイルが SSOT。

各カテゴリを diff に対して検証する:

| # | カテゴリ | 主な確認コマンド |
| --- | --- | --- |
| 10-1 | 前提の検証（要件・慣習・ビジネスルール一致） | コードベース grep |
| 10-2 | もっともらしいが間違っているコード（import 存在・API バージョン・配線漏れ） | grep で import 先・呼び出し元確認 |
| 10-3 | コピペパターン（同一実装の別名、同種実装の既存 grep 確認） | grep で類似実装確認 |
| 10-4 | 冗長な条件分岐（同関数・引数違いだけの if/else） | diff 目視 |
| 10-5 | Callback + 外部変数キャプチャ（コールバック内外部変数代入） | diff grep |
| 10-6 | スコープクリープ（未依頼機能・不要抽象化・未指示レガシーサポート） | diff 目視 |
| 10-7 | デッドコード / 未使用コード（import・export・到達不能分岐・TODO） | grep で呼び出し元 0 件確認 |
| 10-8 | フォールバック / デフォルト値濫用（`??`・`\|\|`・空 catch） | diff grep `\?\?` `\|\|` `catch` |
| 10-9 | レビュー指摘への不適切な対応（修正でなくテスト追加で誤魔化し）| 2 回目以降のみ確認 |
| 10-10 | Stateful Regex（`/g` フラグ regex を `test()` で使用） | grep `/g` regex |
| 10-11 | コンテキスト適合性（命名・エラーハンドリング・ログ・テストスタイル） | grep で既存パターン比較 |

`10-9` は 2 回目以降のみ。`rules/core-standards.md`「AI 生成コード検証」を参照して REJECT 基準を確認する。

### 11. エラー状態チェック（React/Next.js ファイルがある場合）

**狙い**: Loading/Error/Empty/Normal の 4 状態が正しく区別されているか。

- `isError` が適切に UI に反映されているか
- Loading 中にコンテンツが一瞬表示されないか（`router.isReady` 前に fetch が走っていないか）
- `data: 0` と `error` を混同していないか（空状態と エラー状態を明確に区別）
- 4 状態すべてが Storybook で story 化されているか

React/Next.js ファイルがない場合は N/A。

## 実行フロー

### Phase 1: 対象変更の把握

```bash
git diff --name-status main...HEAD
git diff --stat main...HEAD
```

変更ファイルのうち、以下を対象候補としてリストアップ:

- 新規作成した features / components / hooks / types
- 削除したコンポーネント
- 変更した共有コンポーネント

### Phase 2: 11 カテゴリの自己チェック

各カテゴリについて Finding を作成（問題なければ `resolved`、問題があれば `new`、対象ファイルなければ `N/A`）。

記録の判定基準:

- `N/A` = カテゴリの対象自体が変更に存在しない（削除なし・React ファイルなし等）
- 対象はあるが確認手段がない（参照先ファイル・Linear・Figma にアクセス不能）→ `N/A` とせず「確認不可」として理由を記録する。確認不可は BLOCKED の根拠にしない
- カテゴリ 7 の severity 目安: PII 風データが本番バンドルに載る経路にあるなら `critical`、モック層に留まるが配置規約違反なら `major`

```
PRC-001 [resolved] 関連 Issue 合意事項確認
  - 親/兄弟 Issue 確認済み、URL クエリ値はプロジェクト既定値に準拠

PRC-002 [new] AI アンチパターン 10-2 配線漏れ
  - options.format を受け取る経路が追加されたが呼び出し元から渡されていない
  - 修正: src/foo.ts:42 の呼び出し元に format を追加
```

### Phase 3: 修正と再チェック

`new` / `persists` が残っていたら修正してから、もう一度このスキルを回す。

3 周目も同じ finding が残るなら、そのカテゴリのアプローチ自体を再考する（ユーザーに相談）。

### Phase 4: 重複・簡素化パス

自己チェックが通ったコードに対して機械的なクリーンアップを回す:

1. `/similarity-check` — 変更ファイルを対象に AST ベースの重複検出。本質的な重複が出たら統合する
2. `/ponytail-review` — 過剰実装だけを狙う検出（標準ライブラリの再実装・不要な依存・投機的な抽象化・使われない拡張点）。報告のみなので削除は自分で適用する。消す判断が先、磨くのは後
3. `/simplify` — 変更コードの reuse / simplification / efficiency フィックスを適用する（組み込み skill が存在しない環境ではスキップ）

このフェーズでコードを修正した場合、影響するカテゴリ（特に 10-3 コピペ / 10-7 デッドコード）のみ再チェックする。

### Phase 5: Output

全 Finding が `resolved` / `N/A` になったら以下を出力:

```
Pre-Review Check: PASSED
- 検証したカテゴリ: 11 / 11
- Finding: N 件（すべて resolved）
- similarity-check / ponytail-review / simplify: 実行済み（修正 N 件）
- /codex:review に進んで OK

または

Pre-Review Check: BLOCKED
- 残 Finding:
  - PRC-00X [new] <タイトル>
  - PRC-00Y [persists] <タイトル>
- /codex:review に進む前に上記を解決する
```

## Output Contract

```markdown
# Pre-Review Check: <PASSED|BLOCKED> (Iteration #N)

## Summary

- 変更ファイル数: N
- 検証カテゴリ: 11 / 11
- Finding: N 件 (new: N, persists: N, resolved: N, N/A: N, 確認不可: N)
- similarity-check / ponytail-review / simplify: <実行済み（修正 N 件）| スキップ（理由）>

## Findings

| finding_id | Category | Status | Severity | File:Line | Issue |
| --- | --- | --- | --- | --- | --- |
| PRC-001 | 2. ドメイン型整合 | new | major | `src/foo.ts:42` | 説明 |

## Category Summary

Result 欄は `PASS` / `FAIL` / `N/A` / `確認不可（理由）` の 4 値。

| # | Category | Result | Findings |
| --- | --- | --- | --- |
| 1 | Linear Issue 合意事項 | PASS | - |
| 2 | 既存ドメイン型・語彙整合 | PASS | - |
| 3 | 削除コンポーネント機能棚卸し | N/A | 削除なし |
| 4 | Figma デザイン要素逆引き | PASS | - |
| 5 | UI variant × type サポート | PASS | - |
| 6 | 未実装ボタン | PASS | - |
| 7 | ダミー / PII 風データ | PASS | - |
| 8 | プロジェクト慣例準拠 | PASS | - |
| 9 | セキュリティ sink | PASS | - |
| 10 | AI アンチパターン 11 カテゴリ | FAIL | PRC-001 |
| 11 | エラー状態 (4 状態) | N/A | Reactファイルなし |

## Next Action

- PASSED: `/codex:review` に進む
- BLOCKED: 上記 Finding を解決してから再度 `pre-review-check` を回す
```

### Severity レベル

| Severity | 定義 |
| --- | --- |
| critical | 本番障害リスク、セキュリティ問題 |
| major | REJECT 基準該当、バグ |
| minor | 改善推奨だがブロッキングではない |

### 判定ルール

- `critical` または `major` の finding が 1 件でもあれば **BLOCKED**
- BLOCKED の場合は `/codex:review` に進む前に修正すること
- `minor` のみなら **PASSED**（改善推奨として記録）
