# テレメトリ正規化と契約

## Canonical Fields

取得したイベントから、次の canonical fields に正規化する。プロバイダ固有の `release.commit`、`git_sha`、`build_commit` などは、値の出所を記録したうえで `commit` に対応付ける。

| Field | 必須度 | 用途 |
| --- | --- | --- |
| `commit` | exact build には必須 | production で動いていたソースの特定 |
| `filename` | exact location には必須 | 生成物の相対パス。例: `build/server/index.js` |
| `lineno` | exact location には必須 | 生成物内の行番号。1始まりとして扱う |
| `function` | 推奨 | 例: `loader$30`。行付近の候補照合 |
| `colno` | 任意 | 列番号。minify時の補助情報 |
| `release` / `environment` | 推奨 | build・runtime差分の評価 |
| `workspace` / `package` / `build_command` / `runtime` | あれば使用 | monorepo・production build recipe の特定 |

併せて次を取得する。
- エラーメッセージ、例外種別、stack trace
- event数、影響ユーザー数、first seen、last seen
- release、environment、region、feature flag、request URL（secretや個人情報は除外）
- breadcrumbs、request/response の要約
- telemetry の取得元と、欠落している canonical field

`commit` がない場合は commit ベースの再構築を実行しない。`filename` または `lineno` がない場合は stack trace 等による fallback 調査として明示し、現在の build の行番号を production の行番号とみなさない。

## 推奨テレメトリ契約

Sentry 側に次の build metadata を載せると、Source Mapsなしの再構築が可能になる。値は source code や secret ではなく、生成物の座標だけにする。

```json
{
  "build.commit": "1234abcde",
  "build.filename": "build/server/index.js",
  "build.function": "loader$30",
  "build.lineno": 14150,
  "build.colno": 0,
  "build.release": "<release>",
  "build.environment": "production"
}
```

Sentry の tags/contexts に載っている build metadata を上記 canonical fields に正規化する。`build.commit`、`build.filename`、`build.lineno` の3つが揃わない場合は、exact reconstruction 不可としてレポートする。
