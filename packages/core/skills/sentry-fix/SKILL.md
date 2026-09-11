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
- このスキルは deployment 済みの Source Maps に依存しない。ローカル build で Source Maps が生成される可能性はあるが、外部へ upload しない。生成・uploadの状態は確認できた事実だけを記録する。
- commit・filename・lineno が欠けている場合、現在の `HEAD` を代用して「特定できた」と言わない。欠落したテレメトリと信頼度をレポートする。
- テレメトリ、ログ、build 出力に含まれる token・cookie・API key・個人情報は必ず redact する。
- build workspace に Sentry、Linear、GitHub、cloud provider 等の認証情報を継承しない。依存関係取得にネットワークが必要な場合は、credential-free の隔離環境で明示確認を得てから実行する。

## モード

| モード | 引数 | 説明 |
| --- | --- | --- |
| 対話モード（default） | `/sentry-fix <url>` | 調査・再構築後に、起票して修正 / 起票せず修正 / 監査のみを選択 |
| 起票して修正 | `/sentry-fix --ticket <url>` | 調査後、Linear の宛先を確認してから起票し、実装へ進む |
| 起票せず修正 | `/sentry-fix --fix <url>` | 調査結果を実装コンテキストにして修正へ進む。Linearには起票しない |
| 監査のみ | `/sentry-fix --audit <url>` | 調査・build・レポートのみ。コードを変更しない |

`--ticket`、`--fix`、`--audit` は「調査後の希望アクション」を指定するだけで、すべて同じ調査フェーズを先に実行する。レポートが出るまで外部書き込みやコード変更を始めない。対話モードではレポート後に必ず3択を提示し、フラグ指定時も指定アクションを選択済みとして確認を取る。`--ticket` でも、Linear の宛先確認と作成確認が終わるまで issue create tool を呼ばない。

## Phase 1: URL とプロバイダの解決

1. URLが Sentry issue/event のものか確認する。未知のURLへ認証付きリクエストを送らない。
2. 接続済み MCP の tool schema / capability を先に確認し、存在しない tool 名や引数を推測しない。ホストに応じて接続済みの MCP を優先する。
   - **Sentry**: 利用可能な resource tool（接続先で `get_sentry_resource(url=<sentry-url>)` が提供される場合はそれ）で issue/event の詳細を取得する。issue URLの場合は代表イベントまたは最新イベントの情報も取得する。
3. プロバイダに接続できない、またはURLからイベントを特定できない場合は停止し、必要な接続・URLを報告する。Linear MCP の有無はこのフェーズの前提にしない。

## Phase 2: テレメトリの正規化

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

## Phase 3: 該当 commit のローカル build

Source Maps を毎回デプロイに含める代わりに、telemetry の `commit` で生成物を再構築する。

### 3.1 build workspace の準備

1. `commit` が full SHA または一意に解決できる short SHA か確認し、値をshell文字列へ補間せず `git rev-parse --verify <commit>^{commit}` 相当で commit object であることを検証する。解決後の full SHA を記録する。telemetry由来のremote URLや任意のrefは使わず、リポジトリで設定済みのremoteだけを使う。
2. commit の detached worktree または disposable build workspace を作る。現在の作業ツリーを変更しない。install/buildは、workspaceだけをwrite対象にするOS sandboxまたはcontainer内で実行し、hostのHOME、他のworktree、SSH agent socket、cloud credentialを見せない。利用可能な隔離機構がなければbuildを実行せず停止する。
3. lockfile と package manager を検出し、`packageManager` 宣言・lockfile・実行バイナリが一致することを確認する。依存関係は frozen/immutable install を使い、lockfileを変更しない。
4. build workspace は credential-free・network-restricted で実行する。依存関係の install script や build script は外部入力由来の実行コードとして扱う。依存関係の取得は lifecycle script を無効にした状態で、設定済みregistryのallowlistに限定する。cacheにない依存関係を取得するためネットワークが必要なら、実行内容と接続先を表示して明示確認を得る。install scriptを有効化する必要がある場合や、production の秘密情報を読み込む必要がある場合は実行せず停止する。環境変数の不足や差分は名前だけを記録する。

### 3.2 framework に応じた build

`next build` を全リポジトリに対して実行しない。まず `package.json`、lockfile、設定ファイル、release/deploy metadata から build system と対象 workspace を判定する。

build recipe の解決順序は次のとおり。monorepoで対象 package が複数ある、または recipe が複数候補になった場合は勝手に選ばず停止する。

1. telemetry / release に記録された deploy metadata
2. commit に含まれる CI・Vercel・deploy 設定
3. 対象 package の package manager script

記録済みの workspace、package、build mode、Node/runtime、package manager、feature flag がある場合は照合し、差分を信頼度に反映する。

| 判定 | 実行 |
| --- | --- |
| Next.js (`next` dependency または Next config) | プロジェクトの build script を優先し、必要なら検出した package manager 経由で `next build` |
| Vite (`vite` dependency または Vite config) | プロジェクトの build script を優先し、必要なら package manager 経由で `vite build` |
| その他 | プロジェクトに定義された build script だけを使う |
| 判定不能 / build scriptなし | build を発明せず、再構築不能としてレポート |

build script と設定を実行前に確認し、deploy、publish、telemetry送信、Source Map upload 等の外部副作用が含まれていないことを検証する。検証できない場合は実行せず、必要な確認事項を報告する。

build について次を記録する。

- 実行したコマンド、package manager、Node/runtime、依存関係の状態
- 成否、実測時間、stderr の要約
- production と異なる環境変数・feature flag・region・runtime
- Source Maps の生成・upload 状態（confirmed / generated locally / not observed / unknown）。unknownを「生成していない」と扱わない

### 3.3 生成物と行番号の照合

1. `filename` が NUL、URL、絶対path、`..`、drive/UNC path を含まない相対POSIX pathであることを確認する。不正な形式は拒否し、stack traceの別fieldを無検証でartifact pathに使わない。
2. buildで確認できた生成物ルートだけを許可する。生成物ルートはcanonicalized build workspaceの厳密な配下にあり、今回のbuildで作成・確認されたsymlinkでないdirectoryであることを先に検証する。その後、artifactのrealpathもその配下であること、symlinkでない通常ファイルであることを確認する。`build/server/index.js` を無根拠に `.next` や `dist` へ読み替えない。
3. exact path が存在しない場合だけ、検出済み生成物ルート内で同一 basename 等の候補を列挙し、複数候補を勝手に選ばない。
4. `lineno` が1以上の整数、`colno` が指定されていれば0以上の整数であることを確認する。不正な値は拒否する。
5. `lineno` の前後（目安 ±30行）を読み、`function` と一致するか確認する。`function` が見つからない場合も、行番号・生成物・commitの一致状況を明示する。
6. 次の evidence をレポートする。
   - commit、生成物ファイル、行番号、function
   - 該当行のコード断片（secret / PII を redact）
   - build workspace の短縮path（ユーザー名を含む絶対pathは出さない）
   - 元ソース候補と、候補に至った根拠

### 3.4 信頼度

| 信頼度 | 条件 |
| --- | --- |
| 高 | telemetry の commit、workspace、build recipe、runtime/package manager が production metadata と一致し、build成功、filename と lineno が exact match |
| 中 | commit・artifact path・line は一致するが、production recipe/環境差分が未解決、または function の照合に失敗 |
| 低 | minified/chunk、候補パス、line out of range、build失敗、または commitなしの fallback |

環境依存の差分、強い minify、chunk分割によって行番号がずれる可能性がある。ずれを検証できない場合は、推測を確定診断として出力しない。
「exact reconstruction」と呼べるのは信頼度が高の場合だけ。commit・path・lineが一致しただけでは「同じproduction artifact」と断定しない。

## Phase 4: 調査レポート

調査後、少なくとも次の形式で出力する。

```markdown
## Production error reconstruction

### Provider / telemetry
- Provider: Sentry
- URL: <redacted if necessary>
- Commit: <sha> (source: <field>)
- Artifact: <filename>:<lineno>:<colno or ->
- Function: <function or ->
- Release / environment: <value>

### Build
- Framework: <Next.js | Vite | other | unknown>
- Command: <actual command>
- Result: passed | failed | skipped
- Duration: <measured duration>
- Workspace / recipe: <package and actual build recipe>
- Environment differences: <list or none>
- Source Maps: confirmed generated locally | not observed | unknown; external upload: not observed | blocked | unknown

### Location evidence
- Resolved artifact: <path or not found>
- Matching line: <line and redacted context>
- Source candidate: <path:line or unknown>
- Confidence: high | medium | low

### Diagnosis
- <observed facts>
- <ranked cause hypotheses, if enough evidence exists>

### Gaps / limitations
- <missing telemetry, build failure, path mismatch, or environment caveat>
```

「修正可能」と断定するのは、原因と変更箇所を evidence から説明できる場合だけにする。build が速くても、成功していない build や別 commit の生成物を根拠にしない。

## Phase 5: ユーザーの選択

対話モードではレポートの後、次の3択を提示する。

### 1. Linearに起票して修正

1. Linear MCPのtool schema/capabilityを確認し、利用可能な検索・作成toolと必須引数を使う。Sentry URL、commit、artifact location、build結果をキーに既存 Linear issue の重複を検索する。
2. Linear の `team`、`project`、`assignee`、`priority`、`labels` を確認する。宛先が設定されていない場合、MCPの暗黙の default に任せずユーザーに尋ねる。
3. 起票内容の draft と宛先を表示し、確認を得る。
4. 確認後にだけ、schema確認済みの Linear issue create tool を必須引数付きで呼ぶ。create tool または必須引数が解決できない場合は作成せず停止する。作成した Linear URL を表示する。
5. Linear task URL と Phase 4 の evidence を `/implement-issue` に渡して実装へ進む。実装後は commit / push / PR作成の前で停止し、公開確認を別に取る。

### 2. 起票せず修正

1. Linear MCP を呼ばない。
2. Phase 4 のレポートを直接のタスク説明として `/implement-issue` に渡す、またはユーザーが指定した実装フローに渡す。実装後は commit / push / PR作成の前で停止し、公開確認を別に取る。
3. build workspace と実装用 worktree を分離する。production commit の detached workspace に修正を書き込まない。
4. commit、push、PR作成は別途確認する。

### 3. 監査・計測だけ

Phase 4 の出力で終了する。コード変更、Linear/GitHub/Sentryへの書き込み、PR作成を行わない。

Sentry issue の resolve も自動実行しない。修正後の再計測や resolve 確認は、ユーザーが別途依頼した場合だけ行う。

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

## 前提条件

- Sentry MCP、または設定済みoriginに対する Sentry API に接続できること
- 対象リポジトリが cwd にあること
- 対象 commit の取得と、lockfileに従ったローカル build が可能であること
- credential-free・network-restricted な build workspace を作れること
- OS sandboxまたはcontainerでworkspace以外を不可視にし、networkを制限できること
- Linear MCP は `--ticket` または対話モードで起票を選んだ場合のみ必要
- `gh` CLI は PR を作成する段階でのみ必要

## 停止条件

- provider のイベントを取得できない
- exact reconstruction に必要な commit がなく、ユーザーが fallback 調査を許可していない
- build が失敗し、生成物を検証できない
- build workspaceを隔離できない、またはhost credentialを除外できない
- filename が安全な相対artifact pathではない
- build recipe、対象workspace、runtime、package managerが複数候補または未解決
- build script の外部副作用を無効化・検証できない
- MCP/APIのschema、read-only scope、設定済みoriginを検証できない
- filename の候補が複数あり、どれかを根拠なく選ぶ必要がある
- Linear の起票先が未確定、または重複 issue の扱いが未確定

停止時も、取得できた telemetry、実行した build、失敗理由、次に必要な情報をレポートする。
