---
description: 実装・レビュー・runtime診断・Git公開操作の基準。該当作業の前に必要な節を明示Readする。
paths:
  - "**/core-standards.md"
---

## コーディング基準

正確さはスピードに優先し、コードの正確性は実装の容易さに優先する。ツール実行はプロジェクト定義のスクリプトを使う。

バグ修正・ロジック変更は対象の失敗テストから始め、green 後に整理する。詳細は `tdd` skill。

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

**バグ修正は症状ではなく根本原因を直す**: 触る関数の呼び出し元を全て `rg` で検索してから編集する。共有関数に 1 つガードを置くほうが呼び出し元ごとに置くより diff が小さく、チケットが名指ししていない兄弟呼び出し元も同時に直る。

意図的に妥協して既知の上限を残す場合（グローバルロック・O(n²) 走査・素朴なヒューリスティック）は、上限と昇格条件を書いたコメントを `ponytail:` プレフィクス付きで残す（ponytail 導入環境では ponytail-debt コマンドが回収する）。

### フォールバック/デフォルト引数の禁止・Resolution Responsibility・Phase Separation

**フォールバック禁止**: (1) 必須データ → エラーを投げる。(2) 全呼び出し元が省略 → 必須にする。(3) 渡す経路がない → パラメータ追加。(4) 不変条件あり → ロード時にクロスバリデーション。(5) 起こり得ないシナリオへの防御コード・エラーハンドリング・validation を追加しない。内部コードとフレームワークの保証は信頼し、検証は境界（ユーザー入力・外部 API）のみで行う。

**Resolution Responsibility**: 早期に確定可能な値は境界で1回だけ解決。同じ優先順位ロジックが2箇所以上 → 専用メソッドに集約。表示・実行・永続化が別々に解決 → 同じ結果を共有。

**Phase Separation**: 入力収集・解釈/正規化・実行・副作用を明確なフェーズに分離。ループ内の分岐が入力解釈なら外に出す。実行関数には `Resolved*` 型に変換してから渡す。

新機能追加時はエントリポイント・ナビゲーションも同じ変更セットで更新する。

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

**Callback + 外部変数キャプチャ**: コールバック内で外部変数に代入 / イベントハンドラ経由で値取得 / 複数コールバックで状態構築 → すべて REJECT。戻り値で受け取る。

**スコープクリープ**: 依頼されていない機能 / 単一実装への早すぎる抽象化 / 明示指示なしのレガシーサポート → REJECT。`.transform()` 正規化・`LEGACY_*_MAP`・`@deprecated` 型定義は明示指示なしで追加しない。

**レビュー指摘**: 修正の代わりにテスト追加 / ドキュメント追加 / 無関係ファイルの変更 → すべて REJECT。

**Stateful Regex**: モジュールスコープの `/g` regex を `test()` で使用しない。`test()` 用は `/g` なし、`replace()` 用は `/g` あり。

**シグネチャ変更後の呼び出し元**: 関数シグネチャ・型を変えたらテストファイルを含めて呼び出し元を `rg` で検索する。tsconfig が tests を除外していると typecheck が通ってしまい、CI か Codex で初めて落ちる。

**単一サンプルで結論しない**: 「未使用」「実装されていない」「全部直った」は網羅探索の結果としてのみ言う。1 箇所見て言わない。報告には実行した検索コマンドを添える（コード・テスト・fixture・YAML・migration を含めたか読み手が判定できるように）。

---

## 過去の教訓（必須事項のみ）

### 独断で消費量・副作用を増やさない

- 勝手に commit / push / PR 作成: commit message 2〜3 パターン + push 先を提示して確認する
- 勝手に base branch へマージ: preview deploy 確認目的の push が壊れる
- 依頼にないリファクタを混ぜる: スコープ厳守。別 PR で提案する
- 長文レポートをユーザー未確認で書き出す: 必要性を先に確認する
- 書き出し先を確認せず新規ドキュメントを作成: 追記先の既存ドキュメント（Linear doc 等）があるか書く前に確認する
- 既存を探さず新規 repo / パッケージ / ツールを作成: 同種の既存を検索して報告してから作る
- 1 台のマシンの利用実績から「未使用」と断定して削除・無効化を提案: 「未使用」判定は根拠（telemetry・grep・git log）と信頼度（HIGH / MEDIUM / LOW）を項目ごとに明示する。単一マシンの telemetry だけなら自動的に LOW で、提案に留めて実行しない
- 一括削除・prune を一覧提示なしに実行: 対象の全ファイル一覧と件数を出し、承認を得てから消す

Codex レビューの扱いは `rules/codex-review-policy.md` SSOT（1回だけ実行、独断再実行・bypass 独断使用禁止）。

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

push 承認フラグ（`approve-push.sh`）は承認した HEAD に紐づき、**HEAD が remote に到達した時点か 30 分（`PUSH_APPROVAL_TTL_SECONDS`）で失効**する。guard 通過時には消費しないので、後続の pre-push hook（unittest / validator / mise の python 依存）が落ちても同じ承認で再 push できる。フラグは `~/.claude/review-gate/` に書くため sandbox 解除は不要。承認は cwd の repo + branch 単位なので、worktree で push するなら worktree 内（`git -C <worktree>` の対象）で承認する。`gh pr merge` / `close` も同型で、`approve-pr.sh <PR番号> "理由"` の承認（番号紐づき・TTL 30 分）と一致する番号を明示した単独コマンドだけが通る（番号省略形は deny）。長い自律ランは最後の push で止まりやすいため、着手前に `harness-doctor.sh`（前提ツール・未管理スキル・ドリフト）を通してから始める。

commit message は heredoc で渡さず、`git commit -F <file>` か `-m` の複数指定で渡す。guard は quote 内の文字列（`git commit -m "... git push ..."`）を無視する一方、heredoc 本体はコマンドとして照合するため（`bash <<EOF` 経由の実行を通さない意図的な仕様）、本文に `git push` / `--no-verify` を書くと自分の commit が block される。

git add / git commit / git push は 1 コマンドずつ実行し、`git add <path> && git commit` や `git commit && git push` のようにチェインしない。PreToolUse hook は add の実行前に走るため、同じ呼び出しの中で stage すると block-secrets-in-commit の staged 検査が対象を取りこぼして deny される。commit の単独実行は danger-rules の git-commit-chain / git-commit-and-push-same-command も要求する。

### 共有 checkout と worktree（並行セッションの作業を壊さない）

複数の Claude セッションが同じリポジトリで同時に動いている前提で振る舞う。main の checkout（`gwm` の main_repo）は全セッションが共有する領域なので、そこでは編集も commit もしない。作業は必ず worktree（`EnterWorktree(name: <branch>)`）で行う。

| - `git stash` / `git stash drop | clear` / `git checkout -- <path>` / `git checkout .` / `git restore <path>` / `git reset --hard` は、その checkout にある**他セッションの未 commit 変更も巻き込む**。worktree の外では実行しない。worktree 内でもユーザー指示による破棄か確認する（danger table の `git-stash` / `git-checkout-discard` / `git-stash-discard` rule が warn / block する） |
- worktree 作成前に `git status --short` で共有 checkout が clean か確認する。dirty なら誰の変更か分からないので触らず、ユーザーに報告する
- **stacked PR の base は着手前に確定して表示する**: 既存 PR の上に積むときは `gh pr view <n> --json headRefName,headRefOid` で head を取り、`git fetch origin --prune` 後にその SHA と `git log --oneline -3 <base>` を出して「この上に積む」と明示してからブランチを切る。`gwm` は既定で origin/main から切るので、stacking では base の指定を省略しない

### main 直 commit の回収手順

main への push は通らないので、ローカル main に commit してしまったら**放置せずその場で PR に載せ替えてから作業を終える**（放置すると次の `git pull` が diverge して他セッションが詰まる）:

1. 関連する未 commit の変更（テスト修正等）も同じ作業の一部として commit する
2. `git push origin HEAD:refs/heads/<branch>` で remote に feature branch を作る（ローカルでのブランチ作成は gwm 制約で block されるため、この形式を使う）
3. `git switch <branch>` → PR 作成 → `git switch main && git reset --hard origin/main`（commit は branch に保持済み）

### Issue tracker の規約

issue は **Linear**、PR は **GitHub**。`triage` / `to-issues` / `implement-issue` 等の skill 本文は upstream 由来で `gh` の例を書いているが、issue 側の操作は Linear MCP tool（`list_issues`, `save_comment` 等）に読み替える。

（この規約を vendored skill 本文に書き戻さない。upstream 同期のたびに消えるため、harness 側の rules が SSOT）

### 「確認した」と言う前に実物を見る

すべて REJECT: 実画面（ブラウザ / Storybook）を開かずに完了宣言する、Figma と実装のスクショを突き合わせず「デザイン通り」と報告する、docs / Linear / GitHub issue を引かずに「直しました」と断言する、subagent の「完了しました」をそのまま転記する（成果物ファイルの実在と diff を確認してから完了と言う）。OK は実物のスクショ / ログ / DOM / DB を見た上で差分を提示した場合だけ。

報告する主張は、このセッションのツール結果と突き合わせてから書く。未検証の項目は「未検証」と明言する。

完了報告の形式:

- 「done」「テスト通った」「CI green」は、**同じ turn でそのコマンドを実行し生出力を見た**場合にだけ書く。前の turn の結果や、diff から推測した結果を根拠にしない
- 完了報告の末尾に検証結果を列挙する（typecheck・test・lint・validator・CI のうち該当するもの）。1 検査 1 行で、検査名・実行したコマンド・末尾出力の数行・判定（PASS / FAIL / BLOCKED）を並べる。表にすると応答をコピペした先で崩れるので使わない
- sandbox・credit・permission・hook で検証が実行できなかった項目は **BLOCKED**（PASS でも FAIL でもない第三の状態）として書き、要約文でも「未検証あり」と言う。1 行でも BLOCKED / FAIL があれば「完了」とは書かない
- issue / PR の状態や「マージ済みか」は、Linear や PR 本文の説明ではなく `gh pr view` / `git log` / `git branch --contains` の出力で確定する

バグ修正の完了判定は「元の症状を再現する手順を、修正後に再実行して消えた」ことで行う。「PR をマージすれば直るはず」「この変更で直るはず」は検証ではない。再現手段が無い場合はその旨を明言して完了宣言しない。

### 表面的修正・合意事項

同じ問題に同じ対処を繰り返す → REJECT。「一旦動くようにした」で終わらない。

設定・ツーリングのバグは、パッチを当てる前に**その値を所有する層**（SSOT）を特定する。生成物・配布物・pin された artifact（配布済み config、model catalog の JSON 等）を直接直しても再生成で消える。ソース側を直して配布を再実行する。

ユーザーが一度言ったことは最初に決定した仕様として扱う。

### トークン消費を無駄にしない姿勢

Bash はコマンド先頭に `cd <絶対パス> &&` を置かない（auto mode の classifier に拒否される。`git -C` / `pnpm -C` / 絶対パス起動を使い、cwd が要るなら subshell に入れる。hook でブロック）。検索は Grep ツールを使う。Grep ツールが無いコンテキスト（一部 subagent）では ripgrep を使う（Bash の grep/sed/awk は hook でブロック）。出力を削るプロキシを挟んでいる環境では hook が Bash コマンドを自動で書き換えるので、こちらから経由先を指定しない。パスは推測して Read しない（Glob / ls で確認してから）。既存ファイルへの Write / Edit は同じセッション内で Read 済みの内容にだけ行い、`File has not been read yet` / `modified since read` の precondition エラーは同じ引数の retry では解消しないので対象範囲を Read し直してから再実行する。cloud セッション由来の `/home/user/...` パスをローカルで使い回さない（ローカルは `~` 配下）。同じ情報を複数回取得しない。`get_design_context` を大きな親ノードに一発で打たない（`get_metadata` で分割してから）。codex review / pre-review-check は勝手に複数回走らせない。

### macOS 環境の罠（実際に再発したもののみ）

- `xargs -a` は BSD xargs に無い。`< file xargs` を使う
- 一括置換は実行前後でマッチ件数を突き合わせて取りこぼしを検証する（hidden dir・ignore 設定で検索対象が変わるため件数一致を前提にしない）
- toolchain はプロジェクトのバージョン管理ツール経由で実行し、長い作業の前に解決されたバージョンを確認する

### 既存機能・優先順位・commit戦略

| 項目 | 基準 |
| --- | --- |
| 優先順位 | 新機能より既存の差分修正・バグ修正を先にやる |
| commit 単位 | 問題発見 → 全体を `rg` で検索 → 同種を全て修正 → まとめて commit。論理的に独立した変更は 1 commit に寄せず分割する（分割案を提示して確認） |

### 指示の忠実な実行とスコープ管理

- 「全部消せ」: 代替案を出す前にまず消す
- 「気になる」: 質問であり削除 / 変更の指示ではない
- 「どれにしますか？」と選択肢を並べるより、推奨案を実行するほうが求められている
- 質問への回答中に見つけた隣接問題: 直さない。回答の末尾に「提案」として列挙する
- 質問（「〜は設定された?」「壊れる?」）: Read / Grep / `gh` / `git` の読み取りだけで答える。worktree・ブランチ・ファイルの作成は「編集」と同じ扱いで、実装依頼が来るまで行わない
- formatter / lint --fix: リポジトリ全体に掛けない。`git diff --name-only` で得た変更ファイルだけを対象にする
- 「X を片付けて」の X は依頼の対象だけ。同じ場所にある別ブランチ・別 worktree の作業を同じ PR に混ぜない

**同じ方向性に 2 回 pushback されたら、3 回目の説明を書かずに止まる。** 説明を足しても伝わらないのは論点がずれているサイン。問題を 1 文で定義し直し、判断軸付きで 2〜3 案を出して選ばせる（「話が混ざってる」「で?」「そもそも何がしたいの」が 2 回出た時点で該当）。

### 再発バグは /diagnosing-bugs を強制起動する

初回の bug 報告は通常通り対応する。同じエラーメッセージ / スタックトレース / 画面挙動の 2 回目、または「またこれ」「同じバグ」「前にも見た」が出た時点で表面修正を REJECT し、`/diagnosing-bugs` を Phase 1 から回す。パラメータ調整・条件分岐追加だけの「動くようにした」も REJECT で、根本原因まで掘る。

ユーザーが「また」「同じ」「前に直した」と言ったら自己診断を発動。同一ファイル/関数で2回目以降の修正 → 構造的問題を疑い `/improve-codebase-architecture` も検討。

### Claude sandbox の既知の制約

Git の remote 操作・`gh` は credential 読み取り、`codex-companion.mjs` / `codex app-server` は SQLite 初期化が sandbox で失敗する場合がある。権限エラーと認証切れを区別し、必要な操作を runtime の承認経路で再実行する。一時ファイルは `$TMPDIR` を使う。配布先の write deny は SSOT-first の境界なので解除せず、配布元を修正する。
