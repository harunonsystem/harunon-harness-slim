# ローカル再構築とビルド仕様

Source Maps を毎回デプロイに含める代わりに、telemetry の `commit` で生成物を再構築する。

## 1. build workspace の準備

1. `commit` が full SHA または一意に解決できる short SHA か確認し、値をshell文字列へ補間せず `git rev-parse --verify <commit>^{commit}` 相当で commit object であることを検証する。解決後の full SHA を記録する。telemetry由来のremote URLや任意のrefは使わず、リポジトリで設定済みのremoteだけを使う。
2. commit の detached worktree または disposable build workspace を作る。現在の作業ツリーを変更しない。install/buildは、workspaceだけをwrite対象にするOS sandboxまたはcontainer内で実行し、hostのHOME、他のworktree、SSH agent socket、cloud credentialを見せない。利用可能な隔離機構がなければbuildを実行せず停止する。
3. lockfile と package manager を検出し、`packageManager` 宣言・lockfile・実行バイナリが一致することを確認する。依存関係は frozen/immutable install を使い、lockfileを変更しない。
4. build workspace は credential-free・network-restricted で実行する。依存関係の install script や build script は外部入力由来の実行コードとして扱う。依存関係の取得は lifecycle script を無効にした状態で、設定済みregistryのallowlistに限定する。cacheにない依存関係を取得するためネットワークが必要なら、実行内容と接続先を表示して明示確認を得る。install scriptを有効化する必要がある場合や、production の秘密情報を読み込む必要がある場合は実行せず停止する。環境変数の不足や差分は名前だけを記録する。

## 2. framework に応じた build

`next build` を全リポジトリに対して実行しない。まず `package.json`、lockfile、設定ファイル、release/deploy metadata から build system と対象 workspace を判定する。

build recipe の解決順序:
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

## 3. 生成物と行番号の照合

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
