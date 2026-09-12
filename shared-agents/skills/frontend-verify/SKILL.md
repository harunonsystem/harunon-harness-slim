---
name: frontend-verify
description: フロントエンドUIをheadlessブラウザでスクリーンショット検証する。「UI確認」「スクショ撮って」「見た目チェック」で起動。
---

# フロントエンド検証（agent-browser）

`agent-browser`（headless）で対象ページを開き、構造とスクリーンショットを確認する。ユーザーの画面にウィンドウは出さない。MCP 版ブラウザツールは使わない。

ユーザーの実ブラウザ（ログイン済みタブ・拡張の挙動・実描画）での確認を明示的に求められた時だけ、OpenCLI の `bind` に切り替える（`/opencli-browser` のポリシーに従う。ユーザーのブラウザを起動・前面化しない）。

## 基本フロー

```bash
agent-browser open http://localhost:3000
agent-browser wait 2000
agent-browser snapshot
agent-browser screenshot /tmp/verify.png
```

撮影した画像を Read ツールで確認し、レイアウト、文字の切れ、インタラクションを報告する。詳細なコマンドは `agent-browser skills get core` を参照する（CLI 同梱でバージョン一致）。

## フルページ・注釈・viewport

```bash
agent-browser screenshot --full /tmp/fullpage.png
agent-browser screenshot --annotate /tmp/annotated.png
agent-browser viewport 390 844 && agent-browser screenshot /tmp/mobile.png
agent-browser viewport 1024 1366 && agent-browser screenshot /tmp/tablet.png
agent-browser viewport 1920 1080 && agent-browser screenshot /tmp/desktop.png
```

## インタラクション後の検証

```bash
agent-browser snapshot
agent-browser click @e3
agent-browser wait "完了"
agent-browser snapshot
agent-browser screenshot /tmp/after-click.png
```

`@eN` の ref は画面遷移や DOM 更新で無効になる。操作後は必ず snapshot を再取得する。フォーム操作では `fill` / `type` 後に値を確認する。

## 検証レポート形式

```markdown
## UI検証レポート

### 確認URL
- http://localhost:3000/path

### スクリーンショット
- /tmp/verify.png

### 確認結果
- [ ] レイアウト崩れがないか
- [ ] テキストの切れ・はみ出しがないか
- [ ] インタラクティブ要素が正しく表示されているか
- [ ] レスポンシブ対応が適切か

### 検出された問題
1. [問題の説明]

### 問題なし / 問題あり
```

## 終了

```bash
agent-browser close
```

画像に token、Cookie、個人情報が含まれる場合は共有・commit せず、検証後に削除する。
