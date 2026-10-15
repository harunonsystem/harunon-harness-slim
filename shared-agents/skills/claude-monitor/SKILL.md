---
name: claude-monitor
description: Claude Code の Monitor ツールでバックグラウンドプロセス（CI完了、Devサーバーエラー、テスト進捗）をリアルタイム監視する。「CI監視」「サーバー監視」「ログ監視」「Monitorして」等で使用。
---

# claude-monitor - Claude Code バックグラウンド監視

Claude Code 組み込みの `Monitor` ツールを活用し、セッションをブロックせずにバックグラウンドプロセス（CI、開発サーバー、長時間テスト等）の stdout をリアルタイム監視する。

監視中も Claude はユーザーとの対話や別ファイルの編集など他作業を並行して継続できる。

## pnpm 必須規約（最重要）

pnpm 環境（`pnpm-lock.yaml` が存在する場合）では、バッファリング遅延やコンテキスト浪費を防ぐため以下を徹底する：

1. **バナー抑制**: `pnpm -s run <script>`（または `--silent`）で実行し、`> package@version` などのヘッダー出力を排除する。
2. **ワークスペース即時フラッシュ**: ワークスペースで複数パッケージを並列起動する場合は必ず `--stream` を付与する（例: `pnpm -s -r --parallel --stream run dev`）。
3. **ANSI 装飾排除**: `FORCE_COLOR=0` または `--color=never` を付与し、ANSI エスケープコードによる grep すり抜けやトークン消費を防ぐ。
4. **ディレクトリ移動**: `cd <dir> &&` は hook で禁止されているため、サブディレクトリ対象は必ず `pnpm -C <dir>` を使用する。
5. **テストの非対話化**: `CI=true pnpm test -- --watch=false` のように watch モードを無効化する。

## コマンド構成ルール

- **パイプ時の即時フラッシュ**: `grep` でフィルタリングする場合は必ず `--line-buffered` を付与する（忘れるとバッファリングにより通知が停止する）。
- **既存ログのスキップ**: ログファイルを監視する場合は `tail -n 0 -f` を用いる。
- **一時的エラーのハンドリング**: ネットワークポーリング等は `|| true` や `2>/dev/null` で握りつぶし、スクリプトが途中で異常終了しないようにする。
- **同時起動上限**: 同時に動かす Monitor は 1〜2 本に抑え、具体的な `description` を付与する。

## 定型ユースケース

### 1. CI / PR 完了監視（ワンショット）

PR 作成後や push 後の CI 完了を非同期で監視する。

- `timeout_ms`: `1800000`（30分）
- `persistent`: `false`

```bash
while true; do
  status=$(gh run view <run-id> --json status,conclusion -q '.status + " " + (.conclusion // "")' 2>/dev/null || echo "pending")
  case "$status" in
    completed\ success)
      echo "CI_FINISHED: SUCCESS"
      break
      ;;
    completed\ *)
      echo "CI_FINISHED: $status"
      break
      ;;
  esac
  sleep 30
done
```

### 2. ローカル Dev サーバーのエラー常時監視

開発サーバーを起動し、コード編集に伴うエラー・例外のみを常駐監視する。

- `persistent`: `true`

```bash
# 通常プロジェクト
FORCE_COLOR=0 pnpm -s run dev 2>&1 | grep --line-buffered -iE "error|exception|failed|syntax error"

# ワークスペース配下
FORCE_COLOR=0 pnpm -s -C apps/web run dev 2>&1 | grep --line-buffered -iE "error|exception|failed"
```

### 3. テストスイートの Fast-fail 監視

長時間のテスト実行時、全件終了を待たずに失敗を即時検知する。

- `timeout_ms`: `600000`（10分）
- `persistent`: `false`

```bash
CI=true FORCE_COLOR=0 pnpm -s test -- --watch=false 2>&1 | grep --line-buffered -E "^(FAIL|Tests:|Test Suites:)"
```
