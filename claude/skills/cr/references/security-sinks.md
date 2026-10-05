---
description: セキュリティ REJECT 基準の sink 詳細表。review-policy.md から参照され、security-reviewer subagent 定義経由でレビュー時に読み込まれる（cr スキル本文からの直接参照はない）。
---

## セキュリティ sink 詳細（レビュー時参照）

以下は調査対象の候補である。変更 diff の入力 source・sink・権限境界・既存の検証を辿り、具体的な入力で不正実行・越権・情報流出が起きる根拠を確認した場合は REJECT。根拠 path/line、期待/実際、反例を添える。sink の存在や直前コメントの欠如だけで確定しない。安全な代替や境界検証を要求し、コメントは実装の安全性の代用にしない。

### コード注入 / コマンド実行

| sink | 安全な代替 |
| --- | --- |
| `eval()` / `new Function(body)` への文字列補間 | JSON.parse / ast.literal_eval / 安全な式パーサ |
| JS `child_process.exec` / `execSync` | `execFile`/`spawn` に引数配列で渡す（shell 不使用） |
| Python `os.system` / `subprocess(..., shell=True)` | `subprocess.run([...])` 引数リスト |
| Go `exec.Command("sh"/"bash", "-c", ...)` | `exec.Command(prog, args...)` 直渡し |
| GitHub Actions の `run:` に `${{ github.event.* }}` 直挿し | `env:` 経由でクォート |

### XSS（DOM sink）

| sink | 安全な代替 |
| --- | --- |
| `.innerHTML=` / `.outerHTML=` / `insertAdjacentHTML` / `document.write` | `textContent` / DOMPurify |
| React `dangerouslySetInnerHTML` | サニタイズ必須（DOMPurify） |
| SRI 無しの外部 `<script src>` | `integrity="sha384-..." crossorigin` を付与 |

### 安全でないデシリアライズ

| sink | 安全な代替 |
| --- | --- |
| `pickle`/`cPickle`/`cloudpickle`/`dill`/`marshal`/`shelve`/`joblib.load`/`pandas.read_pickle`/`numpy(allow_pickle=True)` | JSON / msgspec / スキーマ検証デシリアライザ |
| `yaml.load` / `yaml.unsafe_load` | `yaml.safe_load` + スキーマ検証 |
| `torch.load`（既定 `weights_only=False`） | `weights_only=True` |
| stdlib XML（`ElementTree`/`minidom`/`xml.sax`） | `defusedxml` |

### 暗号 / 通信

| sink | 安全な代替 |
| --- | --- |
| Node `crypto.createCipher`（IV 無・MD5 KDF） | `createCipheriv` |
| AES-ECB | AES-GCM または AES-CBC+HMAC |
| TLS 検証無効化 | CA を信頼ストアに追加 |
| ハードコードされたシークレット | env / secret manager 参照 |

### クロスファイル観点

| 観点 | REJECT 条件 |
| --- | --- |
| source→sink トレース | 外部入力が上記 sink へ未検証・未エスケープで到達 |
| 機密の observability 流出 | PII / 認証情報が log・trace・例外メッセージへ |
| IDOR / 認可バイパス | リソース取得がリクエスト元の所有権・権限を未検証 |
| SSRF | ユーザー制御 URL が許可されない内部宛先・認証先へ到達し得る。redirect / DNS 解決 / 実行権限を確認（意図した任意公開 URL 取得だけでは確定しない） |
| Path traversal | 許可 root / 権限境界を越えるユーザー制御パスの open/read/write。正規化・symlink 解決後の containment と、元々許可された任意パス操作を区別する |
| CI/CD 信頼境界 | `pull_request_target` 等を branches フィルタ無しで追加 + secrets 読取 |
