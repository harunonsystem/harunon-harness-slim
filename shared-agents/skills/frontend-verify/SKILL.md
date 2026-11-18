---
name: frontend-verify
description: フロントエンドUIをheadlessブラウザでスクリーンショット検証する。「UI確認」「スクショ撮って」「見た目チェック」で起動。
---

# フロントエンド検証（agent-browser）

`agent-browser`（headless）で対象ページを開き、構造とスクリーンショットを確認する。ユーザーの画面にウィンドウは出さない。MCP 版ブラウザツールは使わない。

ユーザーの実ブラウザ（ログイン済みタブ・拡張の挙動）での確認を求められた場合は、headlessの結果を代わりに報告しない。Browser Use v1のローカルChrome接続を試し、できなければ未検証と伝える（下記評価節を参照）。

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

## Browser Use v1との比較（opt-in）

ログイン済みの実Chromeや拡張機能が必要で、本人がその操作を許可した場合に限り、Browser Use v1.0.1 CLIを**ローカルChrome**接続で試す。`agent-browser`のheadless検証ができなかった場合に結果を偽装しない。外部LLMを使う場合は画面内容の送信リスクがある。金融・認証情報の画面は最小限の操作に留める。

インストールは `uv tool install 'browser-use==1.0.1'` と `browser-use skill install`（プロジェクト依存に混ぜない）。CLI/Skillが未導入なら「不可」として比較を中止。Python Agentの既定 `Browser()` はCloudなので使わない。

ローカルChrome接続が可能な環境では、CLIを操作する側のエージェントが公式Skillに従い、例えば次の最小スモークを行える。

```bash
browser-use <<'PY'
new_tab("http://localhost:3000")
print(page_info())
PY
```

比較は同じローカルURL、同じviewport、同じ操作3件（表示・クリック・スクリーンショット）を `agent-browser` と Browser Use で独立に実行する。各々の成功/失敗、証拠（スクリーンショット）、操作回数、経過時間、使用したモデルとトークン費用（把握できる場合）を記録する。片方しか実行できなければ「比較未完了」と明示する。数値が揃う前に、速度・費用・正確性の優位を断定したり既定のブラウザルートを置換しない。

## 終了

```bash
agent-browser close
```

画像に token、Cookie、個人情報が含まれる場合は共有・commit せず、検証後に削除する。
