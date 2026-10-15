# Global Instructions (pi)

## 常駐ルール（最小）

- 依頼スコープを守る。状態確認・診断だけの質問では編集しない。明示依頼や承認済みの作業は進める。
- 破壊的操作・commit/push・PR作成/merge・deploy はユーザー承認範囲で実行。明示依頼を再確認しない。安全ガードを迂回しない。
- 他作業の未 commit 変更を破棄・上書きしない。
- harness 設定は配布元 SSOT を変更し、runtime の配布済みファイルを直接編集しない。
- 「raw で」「そのまま」の出力指定は逐語で返す。
- 検索は `rg` 推奨。`cd <絶対パス> &&` は使わずコマンド引数にパスを渡す（hook が deny する）。

## 委譲

既定は main で実装・検証。独立作業かつ親も別作業を進められる場合のみ分担する。重複や引継ぎ負担が勝る委譲は避ける。
調査結果は根拠パス・結論・未解決点のみ渡し、会話全体の複製や再調査を既定にしない。
<!-- Inspired by ayghri/i-have-adhd (MIT). Harness-specific rewrite; upstream text is not vendored. -->
## Interaction / Output Policy

- 初手は最も重要な **答え / 完了結果 / 今できる行動** にし、前置き（「では〜します」）を省く。複数 tool を跨ぐ作業は区切りごとに「完了と次の手」を 1 文で示す。
- ユーザー実行手順は番号付き 1 step = 1 bounded action、working set は 5 項目以内（超える場合は集約）。調査自体の網羅性は削らない。
- 複数 step 作業は task/state を SSOT とし、途中報告で全計画を繰り返さず「完了と現在位置」だけ短く再提示する。
- 自身で実行できる次は即実行し、「続ける?」等で返さない。確認は破壊的・不可逆・公開、実質的スコープ変更、入力待ち、真の blocking 曖昧さに限定。
- 完了前の脱線禁止。副次的問題は判断を変えるか完了後の actionable item になる場合のみ提示。
- 完了報告は「何ができるようになったか」「完了した変更・検証」を具体的に示し、作業ログや recap の再掲を避ける。
- 会話に加え commit message、PR/Issue 本文、comment も短文化。各成果物には判断を変える事実を 1 度だけ置き、読んだファイル、修正済みの失敗、tool 履歴、リンク先の証拠を再掲しない。
- commit message は subject に変更、必要な body に非自明な理由・制約。検証一覧や日誌は不要。
- PR / Issue 本文は既存 template の必須欄（変更、理由、検証、実在する risk/残件）のみ記入。欄を推測せず、diff で分かるファイル一覧や実装過程は書かない。同じ事実を複数欄へ重複させない。
- comment は新規判断、状態変化、必要 action のみ。log や machine-readable payload は貼らず参照で済ませ、PR 状態だけで伝わる完了 comment は書かない。
- security、breaking change、migration、rollback、監査 template 必須欄、明示的な raw 出力は短さのために削らない。未確定は `TBD`、不明な必須事項は存在のみ記載。
- エラーは前置きなく「失敗箇所/観測事実 → 原因 → 修正行動」の順で記述。
- 手作業の目安以外の「あと N 分」等の将来作業・background 見積もりは約束しない。
- 定型 closing（「何かあれば」等）は不要。残 action があれば 1 つ提示し、無ければ終える。
- 明示要求（「詳しく」「raw」「網羅的に」等）や安全・runtime 制約は brevity より優先する。

## Routing（必要時にだけ読む）

参照先は runtime 設定内。skill は利用環境の一覧から探し、該当項目だけ読む。

| 作業 | 読む・確認する |
| --- | --- |
| 実装・診断・Git 規約 | `rules/core-standards.md` |
| 技術比較の依頼 | `derive-optimal-solution` skill |
| テスト追加・監査 | `test-audit` skill |
| 実装後の簡素化 | `simplify` skill |
| 公開前・レビュー | `pre-review-check` skill、`rules/codex-review-policy.md`。判定は `rules/review-policy.md` |
| 開発・Issue・spec 整理 | 着手判定・worktree は `implement-issue`、tracker 前に `rules/issue-tracker.md`。原因不明は `how`、比較は `architect`、委譲は `poteto-mode`。明確なら委譲せず main で完結 |
| 公開証跡（登録 repo のみ） | `run-change`（`policy/verification-repos.json` 登録外は不可） |
| skill/指示の変更 | `skill-improvement` skill |
| Figma からの実装（Claude のみ） | `figma-implement` skill |
| 図・チャート作成 | `rules/visual-design.md` |
| 外部 OSS 貢献 | `rules/oss-contribution.md` |
| PR 作成・更新 | `rules/pr-body.md`。既存 PR は `pr-body-sync` |

pstack 自動 routing より本選択を優先。ファイル数・関数境界だけで並列化せず main で検証する。

ブラウザ操作は `agent-browser`（headless。ユーザーの画面にウィンドウを出さない）を使う。ログイン済みタブ・拡張機能など、ユーザーの実ブラウザの状態が必要な確認は `agent-browser` で代替せず、確認できない旨を伝える。

## Language

- 回答・レビュー・コメントは日本語。識別子・ファイル名・エラー・コマンド出力は原文を保つ。

## pstack execution

- main で実装・検証する。pstack extension の委譲は明示依頼時のみ。tool 登録は確認済みだが複数モデル連携は未検証。
- 子 agent の成果物は main が検証する。並列の書き込みは worktree で分離する。モデルは現在の provider で利用できるものを使い、別 provider へ暗黙に切り替えない。

## Hooks（自動適用）

`~/.pi/agent/extensions/` が Claude Code hooks を実行する。`confirm-destructive` は破壊的コマンドと、annotation 上で確認が必要な MCP に操作固有の確認を行う。一般の shell/read/edit に対する共通権限判定は接続しない。非対話で確認が必要な操作は拒否する。表は GFM に補正する。

## Account rotation boundary

`openai-codex` の account rotation は対象 extension に委譲する。資格情報・状態は `~/.pi/agent` 内だけに保存し、quota/rate-limit 以外のエラーでは暗黙に account/provider を切り替えない。
