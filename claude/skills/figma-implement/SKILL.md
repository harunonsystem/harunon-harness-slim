---
name: figma-implement
description: Figma MCPからデザイン情報を取得してUIコンポーネントを実装し、自己検証ループで品質を担保する。「Figma実装」「implement design」、FigmaのURL提示などで起動。
metadata:
  mcp-server: figma, figma-desktop
---

# Figma実装ワークフロー

## Step 0: grill-implementation（実装方針の stress-test）

**デザイン情報取得・実装に着手する前に `grill-implementation` スキルを invoke する。** 詳細は `skills/grill-implementation/SKILL.md`。

このフェーズで押さえるべき Figma 特有の軸:

- 既存のどのコンポーネントを再利用するか（プロジェクトの UI コンポーネントディレクトリを確認）
- 新規コンポーネントのディレクトリ・命名・Storybook 配置
- デザイントークンのマッピング（Figma 変数 → プロジェクトトークン、乖離があれば `get_variable_defs` とトークン定義を突き合わせて確認）
- スタイリング方式（プロジェクトの既存方式に合わせる）
- レスポンシブ（SP / PC）、アクセシビリティ、状態変化（hover / focus / disabled）

終了条件: grill-implementation Phase 5 サマリーでユーザー明示承認。スキップ基準は grill-implementation SKILL.md の該当節。

## Step 1: Node IDの取得

**URL提供時**: `https://figma.com/design/:fileKey/:fileName?node-id=1-2` から抽出
- **fileKey**: `/design/` の次のセグメント
- **nodeId**: `node-id` クエリパラメータの値

**figma-desktop MCP時**: URLなしでOK。Figmaデスクトップアプリで選択中のノードを自動使用（fileKeyも不要）。

## Step 2: デザイン情報の取得

`get_design_context(fileKey, nodeId)` でレイアウト・タイポグラフィ・カラー・スペーシングを取得。`get_variable_defs` と `get_code_connect_map` も併用する。

**重要**:
- `get_design_context` の生成コードは実装の土台ではなく、デザイン仕様として扱う
- 取得前に、対象コードベースの技術スタック・スタイリング方式・既存コンポーネント・デザイントークンを確認する
- 大きい親ノードに一発で使わない。`get_metadata(fileKey, nodeId)` でノード構造を確認し、セクション・カード・モーダル・ヘッダー・リストなど独立して実装できる最小単位まで子ノードに分割してから呼ぶ
- レスポンスがトランケートされた場合も同じ手順（`get_metadata` → 子ノード個別に `get_design_context`）で対処する

## Step 3: スクリーンショット取得

`get_screenshot(fileKey, nodeId)` で視覚リファレンスを取得。実装後の比較に使う。

## Step 4: アセットのダウンロード

Figma MCPが返すアセット（画像・アイコン・SVG）をダウンロード。

- `localhost` ソースが返された場合はそのまま直接使用する
- 新しいアイコンパッケージをインポートしない — アセットはFigma MCPから取得
- `localhost` ソースがある場合にプレースホルダーを使わない

## Step 5: 実装

- CSS変数はプロジェクトのデザイントークンのみ使用 — px値のハードコード禁止
- Figma MCP出力（React + Tailwind）はデザイン仕様として扱い、Tailwindクラスはプロジェクトのトークンに置換
- 同梱の `figma-design-system-rules.md` があれば読む。これはextrasのskill-overridesが提供するプロジェクト固有のマッピングで、core単体には含まれない。
  同梱されていない環境では対象プロジェクトのAGENTS.md・rules・トークン定義から対応を確認し、未確定の対応だけ確認する。
- 既存コンポーネントを再利用。デザイントークンが競合する場合はプロジェクト側を優先しつつ、見た目のフィデリティを維持
- まず小さいコンポーネント単位で実装し、最後にページやセクションへ統合する
- Figmaの値をそのまま移植せず、既存のUIパターン・命名・責務分割に合わせて変換する

## Step 6: 自己検証ループ

1. プロジェクト既定のdevサーバーで対象を表示する。Storybookがあれば利用し、ブラウザでスクリーンショットを取得する
2. Step 3のFigmaスクリーンショットと比較
3. スペーシング・サイズ・カラー・レイアウトに差異があればCSS調整して再チェック
4. 受入条件を満たしたら終了。同じ差異が残る場合は原因を調べ、再試行で解消しなければ未解決内容を報告する

## Step 7: 最終検証

プロジェクトで定義された型検査・lint・関連テストを実行し、結果と最終スクリーンショット比較を提示する。
