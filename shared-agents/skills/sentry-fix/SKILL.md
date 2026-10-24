---
name: sentry-fix
description: "Sentry の本番エラー URLからテレメトリと該当 commit のローカル build を照合し、監査・Linear起票・起票なし修正を選べる。「sentry fix」「本番エラー対応」で起動。"
disable-model-invocation: true
---

# sentry-fix

Sentry の本番エラー URLを起点に、デプロイ時の Source Maps に依存せず、エラーが発生した commit の生成物をローカルで再構築して原因を特定する。

## 最重要ルール

- URLを最初の入力にする。URLがない場合はユーザーに尋ね、未解決 issue の一覧スキャンを勝手に始めない。
- `/sentry-fix <url>` は調査・計測・レポートまでの読み取り専用フロー。Linear、GitHub、Sentry に書き込まない。
- Linear チケット作成、コード変更、commit、push、PR作成は、それぞれ明示的に選択・確認された場合だけ実行する。
- 現在の作業ツリーで `git checkout` しない。production commit の再構築には一時的な detached worktree / build workspace を使い、ユーザーの変更を保持する。
- このスキルは deployment 済みの Source Maps に依存しない。ローカル build で生成される可能性はあるが、外部へ upload しない。
- commit・filename・lineno が欠けている場合、現在の `HEAD` を代用して「特定できた」と言わない。欠落したテレメトリと信頼度をレポートする。
- テレメトリ、ログ、build 出力に含まれる token・cookie・API key・個人情報は必ず redact する。
- build workspace に認証情報を継承しない。credential-free の隔離環境で実行する。

## モード

| モード | 引数 | 説明 |
| --- | --- | --- |
| 対話モード（default） | `/sentry-fix <url>` | 調査・再構築後に、起票して修正 / 起票せず修正 / 監査のみを選択 |
| 起票して修正 | `/sentry-fix --ticket <url>` | 調査後、Linear の宛先を確認してから起票し、実装へ進む |
| 起票せず修正 | `/sentry-fix --fix <url>` | 調査結果を実装コンテキストにして修正へ進む。Linearには起票しない |
| 監査のみ | `/sentry-fix --audit <url>` | 調査・build・レポートのみ。コードを変更しない |

`--ticket`、`--fix`、`--audit` は希望アクションの指定のみで、同じ調査フェーズを先に実行する。レポートが出るまで外部書き込みやコード変更を始めない。

## ワークフロー

### Phase 1: URL とプロバイダの解決
1. URLが Sentry issue/event のものか確認する。
2. 接続済み MCP の resource tool（`get_sentry_resource(url=<sentry-url>)` 等）で issue/event の詳細を取得する。
3. 接続できない、またはURLからイベントを特定できない場合は停止し、必要な接続・URLを報告する。

### Phase 2: テレメトリの正規化
取得したイベントから `commit`, `filename`, `lineno`, `function` などの canonical fields に正規化する。
詳細なフィールド仕様と推奨タグ契約は [telemetry-contract](references/telemetry-contract.md) を参照。

### Phase 3: 該当 commit のローカル build と照合
1. `commit` の detached worktree または disposable build workspace を作成。
2. lockfile と framework に応じてローカルビルドを実行し、生成物と行番号を照合する。
詳細な workspace 隔離手順、framework 別ビルド、照合手順は [build-recipes](references/build-recipes.md) を参照。

#### 信頼度判定
| 信頼度 | 条件 |
| --- | --- |
| 高 | commit、workspace、build recipe、runtimeが production と一致、build成功、filename と lineno が exact match |
| 中 | commit・artifact path・line は一致するが、production 環境差分が未解決、または function 照合失敗 |
| 低 | minified/chunk、候補パス、line out of range、build失敗、または commitなしの fallback |

### Phase 4: 調査レポート
調査結果をまとめ、レポートを出力する。出力形式は [report-template](references/report-template.md) に従う。

### Phase 5: アクション選択
対話モードではレポート後、次の3択を提示する（フラグ指定時も確認を経て進む）。
1. **Linearに起票して修正**: 重複検索 → 宛先確認 → 起票 → `/implement-issue` へ引き継ぎ。
2. **起票せず修正**: レポートを直接タスク説明にして `/implement-issue` または指定フローへ引き継ぎ。
3. **監査・計測だけ**: レポート提示のみで終了。コード変更や外部書き込みを行わない。

## 停止条件
- provider のイベントを取得できない / commit が欠落し fallback も未許可
- build 失敗、または workspace の隔離・credential 除外ができない
- filename が安全な相対 path ではない、または候補が複数あり根拠なく選べない
- Linear の起票先や重複 issue の扱いが未確定
