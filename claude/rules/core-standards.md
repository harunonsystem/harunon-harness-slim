---
description: 実装・レビュー・runtime診断・Git公開操作の基準。該当作業の前に必要な節を明示Readする。
paths:
  - "**/core-standards.md"
---

## コーディング基準

正確さはスピードに優先し、コードの正確性は実装の容易さに優先する。ツール実行はプロジェクト定義のスクリプトを使う。

### 変更サイクル

実装を伴う変更は、**資料・契約 → Test → Minimal implementation → Simplify → Verify** の順で進める。工程を満たすためだけの成果物は増やさない。

1. **資料・契約を先に揃える**: Issue の受入条件、ADR、仕様書、schema、README など、対象挙動の既存 SSOT を確認する。documented contract が変わるならコードより先に更新し、古い記述や矛盾を解消する。関連資料が存在しない局所修正のために新規文書を作らない。
2. **Test**: バグ修正・ロジック変更は対象の失敗テストから始める。`tdd` skill が利用可能なら詳細を読む。テスト追加・変更時は `test-audit` を適用し、実装詳細・自明な getter・一行ごとの挙動まで機械的にテストしない。UI 文言や設定だけの変更など、失敗テストで価値を証明できない変更に儀式的な TDD を強制しない。
3. **Minimal implementation**: 受入条件と失敗テストを通す最小の実装だけを書く。将来用の abstraction、fallback、option、互換 shim を先回りして足さない。
4. **Simplify**: green 後、今回触った差分を簡素化の観点で読み直す。不要な複雑性がある非自明なコード変更では `simplify` skill を使う。数行の一意な修正では skill を儀式的に起動せず、その場の確認でよい。観測可能な挙動を保ったまま、不要な抽象・重複・分岐・old path と、変更によって古くなった code / test / docs を整理する。
5. **Verify**: repository が宣言する deterministic checks と受入条件を再実行し、code / test / docs の整合と不要物が残っていないことを最終確認する。

プロジェクトが明示的に「開発中・内部向け」で、外部利用者・永続データ・既存契約に対する互換性や migration 要件がない場合は、古い構造を温存しない。理想形へ直接置き換え、不要になった旧実装・compatibility layer・migration・deprecated path を同じ変更で削除する。公開 API、保存済みデータ、外部 consumer がある場合は、削除前に互換性・migration 要件を確定する。

新機能より既存の差分修正・バグ修正を先にやる。新機能追加時はエントリポイント・ナビゲーションも同じ変更セットで更新する。

### 実装の梯子

実装前に上から順に検証し、成立した最初の段で止める。

1. そもそも存在させる必要があるか（投機的な需要なら作らず、理由を 1 行書く）
2. このコードベースに既にあるか（helper・util・型・パターンを再利用する。書く前に探す）
3. 標準ライブラリで足りるか
4. プラットフォーム標準機能で足りるか（`<input type="date">` > picker ライブラリ、CSS > JS、DB 制約 > アプリコード）
5. 既存依存で足りるか（数行で済むものに新規依存を足さない）
6. 1 行で書けるか
7. ここまで来て初めて、動く最小のコードを書く

梯子は解を縮めるもので、問題の読み込みを縮めるものではない。変更が触る経路を追い切ってから登る。理解を飛ばして小さい diff を出すのは、効率に見える誤答。

**バグ修正は症状ではなく根本原因を直す**: 触る関数の呼び出し元を全て `rg` で検索してから編集する。共有関数に 1 つガードを置くほうが呼び出し元ごとに置くより diff が小さく、チケットが名指ししていない兄弟呼び出し元も同時に直る。問題を 1 つ見つけたら全体を `rg` で検索し、同種を全て直してからまとめて commit する。

意図的に妥協して既知の上限を残す場合（グローバルロック・O(n²) 走査・素朴なヒューリスティック）は、上限と昇格条件を書いたコメントを `ponytail:` プレフィクス付きで残す（ponytail 導入環境では ponytail-debt コマンドが回収する）。

### フォールバック/デフォルト引数の禁止・Resolution Responsibility・Phase Separation

**フォールバック禁止**: (1) 必須データ → エラーを投げる。(2) 全呼び出し元が省略 → 必須にする。(3) 渡す経路がない → パラメータ追加。(4) 不変条件あり → ロード時にクロスバリデーション。(5) 起こり得ないシナリオへの防御コード・エラーハンドリング・validation を追加しない。内部コードとフレームワークの保証は信頼し、検証は境界（ユーザー入力・外部 API）のみで行う。

**Resolution Responsibility**: 早期に確定可能な値は境界で1回だけ解決。同じ優先順位ロジックが2箇所以上 → 専用メソッドに集約。表示・実行・永続化が別々に解決 → 同じ結果を共有。

**Phase Separation**: 入力収集・解釈/正規化・実行・副作用を明確なフェーズに分離。ループ内の分岐が入力解釈なら外に出す。実行関数には `Resolved*` 型に変換してから渡す。

### Model/provider の境界

- **portable 層**: Skills・rules・AGENTS.md は、観測可能な不変条件・境界・停止条件だけを書く。現行の model/provider/version や速度・品質の順位を前提にしない。
- **調整層**: model/provider/effort/latency の選択は target adapter の socket と model-routing の current policy ledger に閉じ込める。portable 層へ逆流させない。
- **交換契約**: `runtime/role/purpose → alias/effort → projection` を交換可能な境界として扱う。profile が無い・選べない場合は明示的にエラーにし、暗黙の model/provider fallback をしない。
- **skill 境界**: skill は全 target に配布する。model-specific な適用範囲は本文に明記し、portable skill に model/provider の現行値を埋め込まない。
- **変更判定**: モデル交換だけなら台帳と投影だけを更新し、共有 Skills・rules・AGENTS.md は変更しない。不変条件・境界が変わるときだけ共有文書を更新する。

### 禁止事項

- **安全機構をバイパスするワークアラウンド**
- **散在するハードコード契約文字列** - ファイル名やconfigキー名は1箇所で定数定義
- **プロジェクトスクリプトを迂回する直接ツール実行**
- **自明なコメント** - コメントは why のみ。what はコードで表現する

---

## AI 生成コード検証

ここで実際に踏んだ失敗だけを列挙する。「存在しない API を呼ぶ」「陳腐化した書き方をする」といった一般的な LLM の失敗論は書かない（判断を狭めるだけで検出には効かない）。

**配線漏れ**: 新パラメータ・フィールドが呼び出し元から実際に渡されているか `rg` で確認する。`options.xxx ?? fallback` が全経路で fallback 側に落ちていないかも見る。

**Callback + 外部変数キャプチャ**: コールバック間の外部変数を介した状態構築は、順序・競合・寿命の契約を確認する。未保証の順序や共有状態に依存して動作が壊れる場合は REJECT し、戻り値で受け取れる処理は戻り値を使う。framework が要求するイベント駆動の state 更新や、所有・寿命が明確な局所状態という理由だけでは REJECT しない。

**スコープクリープ**: 依頼されていない機能 / 単一実装への早すぎる抽象化 / 明示指示なしのレガシーサポート → REJECT。`.transform()` 正規化・`LEGACY_*_MAP`・`@deprecated` 型定義は明示指示なしで追加しない。

**レビュー指摘**: 修正の代わりにテスト追加 / ドキュメント追加 / 無関係ファイルの変更 → すべて REJECT。

**Stateful Regex**: モジュールスコープの `/g` regex を `test()` で使用しない。`test()` 用は `/g` なし、`replace()` 用は `/g` あり。

**シグネチャ変更後の呼び出し元**: 関数シグネチャ・型を変えたらテストファイルを含めて呼び出し元を `rg` で検索する。tsconfig が tests を除外していると typecheck が通ってしまい、CI か Codex で初めて落ちる。

**単一サンプルで結論しない**: 「未使用」「実装されていない」「全部直った」は網羅探索の結果としてのみ言う。1 箇所見て言わない。報告には実行した検索コマンドを添える（コード・テスト・fixture・YAML・migration を含めたか読み手が判定できるように）。

**テストから git を spawn するときは `GIT_*` 環境変数を落とす**: commit hook 配下では親 repo を指す `GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE` が export されており、一時ディレクトリでの `git init` / `git config` が親 repo の `.git/config` を書き換える。`env` から `GIT_` 始まりを除いて渡し、`GIT_DIR=/nonexistent/.git` を与えた実行で再現確認してから commit する。

---

## 過去の教訓（必須事項のみ）

### 指示の忠実な実行とスコープ管理

- 「全部消せ」: 代替案を出す前にまず消す
- 「気になる」: 質問であり削除 / 変更の指示ではない
- 「どれにしますか？」と選択肢を並べるより、推奨案を実行するほうが求められている
- 質問への回答中に見つけた隣接問題: 直さない。回答の末尾に「提案」として列挙する
- 質問（「〜は設定された?」「壊れる?」）: Read / `rg` / `gh` / `git` の読み取りだけで答える。worktree・ブランチ・ファイルの作成は「編集」と同じ扱いで、実装依頼が来るまで行わない
- formatter / lint --fix: リポジトリ全体に掛けない。`git diff --name-only` で得た変更ファイルだけを対象にする
- 「X を片付けて」の X は依頼の対象だけ。同じ場所にある別ブランチ・別 worktree の作業を同じ PR に混ぜない
- issue / PR はプロジェクトで設定された tracker とホスティング先を使う。未設定なら入力 URL とリポジトリの設定を確認し、それでも判断できないときだけユーザーに確認する

ユーザーが一度言ったことは最初に決定した仕様として扱う。

**同じ方向性に 2 回 pushback されたら、3 回目の説明を書かずに止まる。** 説明を足しても伝わらないのは論点がずれているサイン。問題を 1 文で定義し直し、判断軸付きで 2〜3 案を出して選ばせる（「話が混ざってる」「で?」「そもそも何がしたいの」が 2 回出た時点で該当）。

### 独断で消費量・副作用を増やさない

- 勝手に commit / push / PR 作成: commit message 2〜3 パターン + push 先を提示して確認する
- 勝手に base branch へマージ: preview deploy 確認目的の push が壊れる
- 依頼にないリファクタを混ぜる: スコープ厳守。別 PR で提案する
- 長文レポートをユーザー未確認で書き出す: 必要性を先に確認する
- 書き出し先を確認せず新規ドキュメントを作成: 追記先の既存ドキュメント（Linear doc 等）があるか書く前に確認する
- 既存を探さず新規 repo / パッケージ / ツールを作成: 同種の既存を検索して報告してから作る
- 1 台のマシンの利用実績から「未使用」と断定して削除・無効化を提案: 「未使用」判定は根拠（telemetry・grep・git log）と信頼度（HIGH / MEDIUM / LOW）を項目ごとに明示する。単一マシンの telemetry だけなら自動的に LOW で、提案に留めて実行しない
- 一括削除・prune を一覧提示なしに実行: 対象の全ファイル一覧と件数を出し、承認を得てから消す
- 承認済み操作の内訳（commit の分割案・ブランチ名・順序）を聞き直す: 承認を取り直すのは操作の種類が変わるとき（commit の許可で push する、push の許可で PR を作る、削除に踏み込む）だけ。同じ操作の粒度・命名は推奨案で実行して結果を報告する。論理的に独立した変更は 1 commit に寄せず分割し、commit 未承認なら分割案と操作の承認を確認する

Codex レビューの扱いは `rules/codex-review-policy.md` SSOT（1回だけ実行、独断再実行・bypass 独断使用禁止）。

### 「確認した」と言う前に実物を見る

すべて REJECT: 実画面（ブラウザ / Storybook）を開かずに完了宣言する、Figma と実装のスクショを突き合わせず「デザイン通り」と報告する、docs / Linear / GitHub issue を引かずに「直しました」と断言する、subagent の「完了しました」をそのまま転記する（成果物ファイルの実在と diff を確認してから完了と言う）。OK は実物のスクショ / ログ / DOM / DB を見た上で差分を提示した場合だけ。

報告する主張は、このセッションのツール結果と突き合わせてから書く。未検証の項目は「未検証」と明言する。

完了報告の形式:

- 「done」「テスト通った」「CI green」は、**同じ turn でそのコマンドを実行し生出力を見た**場合にだけ書く。前の turn の結果や、diff から推測した結果を根拠にしない
- 完了報告の末尾に検証結果を列挙する（typecheck・test・lint・validator・CI のうち該当するもの）。1 検査 1 行で、検査名・実行したコマンド・末尾出力の数行・判定（PASS / FAIL / BLOCKED）を並べる。表にすると応答をコピペした先で崩れるので使わない
- sandbox・credit・permission・hook で検証が実行できなかった項目は **BLOCKED**（PASS でも FAIL でもない第三の状態）として書き、要約文でも「未検証あり」と言う。1 行でも BLOCKED / FAIL があれば「完了」とは書かない
- issue / PR の状態や「マージ済みか」は、Linear や PR 本文の説明ではなく `gh pr view` / `git log` / `git branch --contains` の出力で確定する
- `pre-review-check` / `ponytail-review` / `simplify` 等の skill を起動せずに「PASSED」「指摘なし」と書かない。自分で観点を見たことは skill の実行ではない（同じセッションで直前に起動していても、次の PR では改めて起動する）

何をもって「直った」「通った」とするか:

- **バグ修正**: 元の症状を再現する手順を、修正後に再実行して消えたことで判定する。「PR をマージすれば直るはず」「この変更で直るはず」は検証ではない。再現手段が無い場合はその旨を明言して完了宣言しない
- **失敗した実行経路で検証する**: 本物の `git push` の pre-push hook で落ちたものは、自分の Bash で直接テストを回して通っても直った証拠にならない（hook 下では python の解決・シグナル・stdin・cwd が違う）。同じ gate で 2 回目に失敗した時点で再試行をやめ、環境差を疑う。「N 回中 N 回失敗」は flaky ではなく決定的で、頻度を数えてから形容詞を選ぶ
- **生成物**（slim 配布など）: 生成の仕組みが動いたことではなく、配布先と同じ条件（別 HOME・main checkout・`/tmp` 外・submodule 無し・`.env` 無し）で生成物自身の検査が通ることで受け入れる。手元の生成 tree 内でテストを回しただけでは足りない
- **設定ファイルの因果**（「push が消している」「ツールが出し入れしている」）: backup の差分やスナップショットでは決めない。backup に無いことはどちらの向きの証拠にもならない。live のコピーに同じ入力を注入して新旧コードで同じ経路を流す実験で決着させる。ユーザーが実体験として断言したことは、自分の推論より優先して検証対象にし、否定しにかかる前に決着する実験を組む。誤った訂正は訂正を重ねず、PR を close して理由を残す

### 表面的修正・合意事項

同じ問題に同じ対処を繰り返す → REJECT。「一旦動くようにした」で終わらない。

- 設定・ツーリングのバグは、パッチを当てる前に**その値を所有する層**（SSOT）を特定する。生成物・配布物・pin された artifact（配布済み config、model catalog の JSON 等）を直接直しても再生成で消える。ソース側を直して配布を再実行する
- 設定ファイルを書いても実行中のプロセスには反映されないことがある（例: Electron の `globalShortcut` は起動時と設定 UI 経由の変更時にしか再登録されない）。「書いたのに効かない」と見えたら、誰がいつそのファイルを読み直すかの反映経路を先に確認する。アプリが管理する設定ファイルは終了時に上書きされうるので、検証はアプリを止めてから行う
- 機構が現役かどうかは、ファイル内コメントや config の記述から推定しない。退役した機構は「唯一の〜」と自称する宣言だけが残ることがある。採用する前に会話履歴・ADR・実際の呼び出し経路のどれかで裏を取る
- 重複解消・deepening の完了条件は削除ベースで置く（実装が 1 つ消えた、呼び出し元からの private 参照が 0 になった）。validator や fixture を足して重複そのものを残す修正は完了ではなく、同じ領域が次のレビューで再び指摘される

### 再発バグは根本原因を調査する

初回の bug 報告は通常通り対応する。同じエラーメッセージ / スタックトレース / 画面挙動の 2 回目、または「またこれ」「同じバグ」「前にも見た」が出た時点で表面修正を REJECT する。`diagnosing-bugs` skill が利用可能なら Phase 1 から回す。未導入なら再現条件とログを集め、呼び出し元を追い、仮説を検証して根本原因の失敗テストから修正する。パラメータ調整・条件分岐追加だけで調査を終えない。

- 同一ファイル・関数で2回目以降の修正なら構造的問題を疑う。`improve-codebase-architecture` skill が利用可能なら調査に使う
- 同じ症状を直す前に、過去に同じ対処が入って revert されていないかを調べる。着手前に `git log --all --grep=<症状>`・`git log -S<識別子>`・`gh pr list --search <症状>` を 1 回打つ。revert された guard をほぼそのまま再実装しかけた実例があり、revert の理由（塞ぎ漏れた経路）を読まずに直すと同じ結果になる

### Git 安全機構

守るべき線は 3 つ:

- `--no-verify` / `-n` で hook を skip しない
- main / master への直接 push・force-push をしない
- シークレットを含むファイル・差分を staged にしない

コマンド安全ポリシーの SSOT は `policy/danger-rules.json`、hook の配線範囲は `policy/hook-pipeline.json` が宣言する（runtime ごとの消費経路と実効 rule はそこを読む）。全ターゲットで同じ hook が同じ判断をすると仮定しない。検出漏れの実例として、omp の `bash.patterns` は `--no-verify` 長形式しか見ず、`-n` 短縮形・結合短フラグ・env prefix は hook 側が第二防衛線として拾う。staged 内容の秘密情報検出は danger table ではなく `verify-before-commit.sh` の責務。

block された場合の責務:

- 原因を直す。hook を skip する形の回避を試みない
- **同じ deny が 2 回出た時点で試行を止め、deny を出した hook スクリプト（`claude-hooks/*.sh`）の該当 rule を読んでから次の手を打つ。** deny メッセージの字面だけを変えた再試行（`&&`→`;`、引数の並べ替え等）は原因を解消しないままトークンを燃やすだけ
- シークレット検出が誤検知に見えても、独断で「誤検知だから無視」と判断しない。検出箇所（ファイル・行・値）を提示してユーザーの判断を仰ぐ
- git コマンドを**題材として書く**ファイル編集（skill の手順書など）は Bash の heredoc や `perl -pi -e` ではなく Edit / Write ツールで行う。guard は実行されない文字列でも Bash に渡るコマンド全体を照合するため、heredoc 本文や `rg` のパターン引数に `git push` があるだけで deny される。guard を「実害が無いから」と回避せず、経路を Edit に変える

commit:

- git add / git commit / git push は 1 コマンドずつ実行し、`git add <path> && git commit` や `git commit && git push` のようにチェインしない。PreToolUse hook は add の実行前に走るため、同じ呼び出しの中で stage すると block-secrets-in-commit の staged 検査が対象を取りこぼして deny される。commit の単独実行は danger-rules の git-commit-chain / git-commit-and-push-same-command も要求する
- commit message は subject と必要な body だけで構成し、`Generated with ...` / `Co-Authored-By: ...` の trailer は runtime の既定テンプレートに含まれていても付けない
- commit message は heredoc で渡さず、`git commit -F <file>` か `-m` の複数指定で渡す。guard は quote 内の文字列（`git commit -m "... git push ..."`）を無視する一方、heredoc 本体はコマンドとして照合するため（`bash <<EOF` 経由の実行を通さない意図的な仕様）、本文に `git push` / `--no-verify` を書くと自分の commit が block される

push・PR の承認:

- push 承認フラグ（`approve-push.sh`）は承認した HEAD に紐づき、**HEAD が remote に到達した時点か 30 分（`PUSH_APPROVAL_TTL_SECONDS`）で失効**する。guard 通過時には消費しないので、後続の pre-push hook（unittest / validator / mise の python 依存）が落ちても同じ承認で再 push できる。例外は remote ref の削除だけの push（`--delete` / `:<ref>`）で、HEAD を送らないため guard 通過時に消費する（main / master の削除は承認でも通らない）。フラグは `~/.claude/review-gate/` に書くため sandbox 解除は不要
- 承認は cwd の repo + branch 単位なので、worktree で push するなら worktree 内（`git -C <worktree>` の対象）で承認する
- `gh pr merge` / `close` も同型で、`approve-pr.sh <PR番号> "理由"` の承認（番号紐づき・TTL 30 分）と一致する番号を明示した単独コマンドだけが通る（番号省略形は deny）
- 長い自律ランは最後の push で止まりやすいため、着手前に `harness-doctor.sh`（前提ツール・未管理スキル・ドリフト）を通してから始める

merge:

- conflict 解決後は commit 前に `git diff ORIG_HEAD` を確認し、意図しない差分がゼロであることを見てから merge commit を作る。ブランチ側で base と同じ内容に戻した箇所は、main 側が同じ箇所を変えていても conflict にならず main 側が黙って採用される（ours が base と無差分のため）。conflict marker の有無は安全の証拠にならない

### 共有 checkout と worktree（並行セッションの作業を壊さない）

複数のセッションが同じリポジトリで同時に動いている前提で振る舞う。main の checkout は全セッションが共有する領域なので、そこでは編集も commit もしない。作業は必ず worktree で行う。runtime の標準機能か、プロジェクト指定の管理コマンドを使い、指定がなければ `git worktree add -b <branch> <path> <base>` を使う。

- `git stash` / `git stash drop | clear` / `git checkout -- <path>` / `git checkout .` / `git restore <path>` / `git reset --hard` は、その checkout にある**他セッションの未 commit 変更も巻き込む**。worktree の外では実行しない。worktree 内でもユーザー指示による破棄か確認する（共有 checkout では `git-discard-in-shared-checkout` が block、worktree 内では `git-stash` / `git-checkout-discard` が warn する）
- worktree 作成前に `git status --short` で共有 checkout が clean か確認する。dirty なら誰の変更か分からないので触らず、ユーザーに報告する
- 自分の未 commit 変更を worktree へ持ち込むときは、共有 checkout で `git stash push -m "<説明>"` → worktree 作成 → worktree で `git stash pop`。stash 直後にツールが「ファイルがディスク上で変更された」と通知するのは stash の結果であり、退避した変更を捨てた版を正として受け入れない
- worktree セッションから `git -C <共有 checkout>` は hook が拒否する。マージ後の main 更新など共有側の操作は worktree を出てから行う。`ExitWorktree` で worktree を消すのは `git status --short` と `git log origin/main..HEAD` が両方空であることを自分で確認してからに限る
- **stacked PR の base は着手前に確定して表示する**: 既存 PR の上に積むときは `gh pr view <n> --json headRefName,headRefOid,baseRefName` で head と merge 先を取り、`git fetch origin --prune` 後にその SHA と `git log --oneline -3 <base>` を出して「この上に積む」と明示してからブランチを切る。親 PR 番号・base branch・子の切り出し点となる親 head SHA を保持する。後で親の変更を子へ取り込んだら、その境界 SHA も更新する。stacking では base の指定を省略しない

stacked PR の `gh pr create` と rebase の直前には、次を確認する。

1. `git ls-remote --exit-code --heads origin "refs/heads/<base>"` と `gh pr view <親PR番号> --json state,mergedAt,baseRefName,mergeCommit` で、base の存在と親の merge 状態・実際の merge 先を確認する。ls-remote の終了コード 2 だけを branch 不在と扱い、通信・認証などの失敗から retarget を決めない。親が未 merge なのに base が無い場合も止めて状況を確認する
2. 親が merge 済みなら、base branch が残っていても実際の merge 先を fetch して新しい base にする。保持した境界 SHA が `git merge-base --is-ancestor <境界SHA> origin/<親のmerge先>` で祖先と確認できる通常の merge なら、その base へ rebase できる。squash / rebase merge などで元の親コミットが祖先にならない場合は、`git rebase --onto origin/<親のmerge先> <境界SHA> <子ブランチ>` で子のコミットだけを移す。境界 SHA が分からない場合は推測して rebase しない
3. `git log origin/<親のmerge先>..HEAD` と `git diff origin/<親のmerge先>...HEAD` で子の変更だけが残ることを確認してから、既存の子 PR は base を変更し、未作成なら新しい base を指定して作成する。base の retarget だけや通常の rebase で squash 済みの親コミットを取り除けたと判断しない

main への push は通らないので、ローカル main に commit してしまったら**放置せずその場で PR に載せ替えてから作業を終える**（放置すると次の `git pull` が diverge して他セッションが詰まる）:

1. 関連する未 commit の変更（テスト修正等）も同じ作業の一部として commit する
2. `git push origin HEAD:refs/heads/<branch>` で remote に feature branch を作る
3. `git switch <branch>` → PR 作成 → `git switch main && git reset --keep origin/main`（commit は branch に保持済み。`--keep` は未 commit 変更を消す場合に止まる）

### トークン消費を無駄にしない姿勢

- Bash はコマンド先頭に `cd <絶対パス> &&` を置かない（auto mode の classifier に拒否される。`git -C` / `pnpm -C` / 絶対パス起動を使い、cwd が要るなら subshell に入れる。hook でブロック）
- 検索は ripgrep（`rg`）を使う（Bash の再帰 grep と `sed -i` は hook でブロック。`sed -n` での読み取りやパイプ内の grep / awk は通る）
- 出力を削るプロキシを挟んでいる環境では hook が Bash コマンドを自動で書き換えるので、こちらから経由先を指定しない
- パスは推測して Read しない（Glob / ls で確認してから）。cloud セッション由来の `/home/user/...` パスをローカルで使い回さない（ローカルは `~` 配下）
- 既存ファイルへの Write / Edit は同じセッション内で Read 済みの内容にだけ行い、`File has not been read yet` / `modified since read` の precondition エラーは同じ引数の retry では解消しないので対象範囲を Read し直してから再実行する
- 同じ情報を複数回取得しない。`get_design_context` を大きな親ノードに一発で打たない（`get_metadata` で分割してから）

### macOS 環境の罠（実際に再発したもののみ）

- `xargs -a` は BSD xargs に無い。`< file xargs` を使う
- 一括置換は実行前後でマッチ件数を突き合わせて取りこぼしを検証する（hidden dir・ignore 設定で検索対象が変わるため件数一致を前提にしない）
- toolchain はプロジェクトのバージョン管理ツール経由で実行し、長い作業の前に解決されたバージョンを確認する
- perl の `s///` でプレースホルダに `@` や `$` を含めない（`@@A` は空配列として補間され、実質 `s/@//` になって全参照が同じ値に潰れる）。プレースホルダは英数字だけのユニーク文字列にし、実行後に残骸ゼロを `git grep` で確認する。rename（staged）と本文置換（unstaged）を分けておくと巻き戻しやすい

### Claude sandbox の既知の制約

- Git の remote 操作・`gh` は credential 読み取り、`codex-companion.mjs` / `codex app-server` は SQLite 初期化が sandbox で失敗する場合がある。権限エラーと認証切れを区別し、必要な操作を runtime の承認経路で再実行する
- 一時ファイルは `$TMPDIR` を使う。配布先の write deny は SSOT-first の境界なので解除せず、配布元を修正する
- lockfile を更新する `pnpm install` は最初から sandbox 外で実行する。sandbox 内ではグローバル store に書けないため pnpm が worktree 内に空の store を作り、全パッケージを一から再取得して 10 分以上止まる（`--prefer-offline` でも同じ）。lint / typecheck / build は sandbox 内で通る
- ブラウザを起動するテスト（Storybook の Chromium 等）は mach port の制約で sandbox 内では起動できない
