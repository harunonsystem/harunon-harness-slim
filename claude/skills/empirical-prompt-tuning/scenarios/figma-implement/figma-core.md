# figma-implement / core単体の差異継続

## 対象

`packages/core/skills/figma-implement/SKILL.md`

## ユーザー入力

ユーザー依頼: このFigma画面の実装を進めるときの手順を、提示済み事実だけでシミュレーションしてください。実ツール実行や編集は不要。
Figma URL・対象nodeのdesign contextとscreenshot・必要assetは取得済み。core単体の配布でfigma-design-system-rules.mdは同梱されていない。プロジェクトAGENTSに使用トークンと既存Buttonのマッピングが定義されており、必要な実装情報は確定済み。Storybookは未導入。dev表示はmake dev-ui、型検査/lint/関連テストはmake verify-uiにまとまっている。
初回のスクリーンショット比較で2pxのずれが出た。原因調査と2回の調整を行っても同じずれが残る、という状況まで入力として与える。
この時点の次の行動・検証と報告内容を短く示してください。実checkout、外部サービス、別agentは対象外。

## 要件チェックリスト

1. [critical] core単体で欠けるExtras overlayを捏造せず、プロジェクト規約へ切り替える
2. [critical] 同じ視覚差異が続く場合に無限再試行せず未解決として報告する
3. [critical] プロジェクトの `make verify-ui` を最終検証として選ぶ

## subagent 投入プロンプト

上のユーザー入力だけを読み、`figma-implement` に従って次の行動を短く返す。Figma・ブラウザ・checkout・変更は行わない。

## 最終実行結果

2026-09-11 fresh評価: 3 critical要件を達成。残る2px差異を未解決として報告。
