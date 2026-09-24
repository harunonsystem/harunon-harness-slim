# Harness orchestration: 条件付き起動

## 対象

`implement-issue`、`grill-implementation`、`figma-implement`、`decompose-issues`、`improve`、`uiux-workflow`、`derive-optimal-solution`。

## ユーザー入力

以下は 2026-09-19 の改訂前に固定したケース。各ケースは独立して実行する。H〜K は初回の改訂評価に使わず hold-out とする。

A implement-issue + grill-implementation: ユーザー「既存API契約どおり age_min/age_max の入力を追加して。配置・UIは隣の価格フィルタと同じ、テストも同じ形式で。実装して」。repo調査で同型の実装と検証コマンドが見つかり、プロダクト判断は未決でない。4ファイル程度。初動を出す。
B grill-implementation: ユーザー「年齢フィルタを追加したい」。repoにUIとAPIの既存契約があるが、年齢不明の利用者を結果に含めるかは決まっていない。初動と最初の質問を出す。
C improve: ユーザー「この30行のparserだけquickで監査、実装しない」。変更対象と直接callerは1つずつ、テスト実行は副作用なし。何を読み、何を成果物にし、委譲するか。
D decompose-issues: ユーザー「この確定済みPRDをIssue案に分解。外部作成はまだしない」。既存の1repoに3つの縦sliceで収まる。要件・MVP・順番は合意済み。調査と確認と委譲をどう進めるか。
E uiux-workflow: ユーザー「既存ボタンの文言を確定済みの日本語に直して」。コンポーネント構造やスタイルは変わらない。どの専門skill/ブラウザ検証が要るか。
F uiux-workflow: ユーザー「チェックアウト画面全体をアクセシビリティとレスポンシブまでレビュー。修正はまだしない」。静的ソースと起動済みheadless検証環境あり、必要skillあり。何を実行し何を報告するか。
G derive-optimal-solution: ユーザー「ジョブキューをDBで持つか外部サービスにするか比較して」。規模と制約は既知。比較結果に何を含めるか。並列化の要否をどう決めるか。

H figma-implement: ユーザーがFigma URLと使用コンポーネント、レスポンシブ方針を指定して実装依頼。配置と遷移も確定。Figma MCP利用可。初動は？
I grill-implementation: ユーザー「この案をインタビューで詰めて、実装前に最終確認して」。技術的な細部は既存コードから解決できるがデータ保存期間が未決。合意後、明示された最終確認をどう扱う？
J improve: 全体監査依頼。独立した2サービス、決済と認証の異なる調査が必要。既存reconは完了。分担の要否と渡すcontext/成果物は？
K implement-issue: 実装中、ユーザー「テスト通った？」。変更依頼と実装承認は既存、merge承認はない。返答後どう進める？PRの追加依頼が来たときにmergeしてよい？

L は追加の reference 境界チェック: Codex上で、承認済みplanのexecute依頼。Claude契約はなくLuna/Solだけ利用可。独立worktree作成可能。planは未commitだがmain側の絶対パスをexecutorから読める。provider選択とplan引継ぎをどうする？実際にspawn/commitせず方針を実演する。

## 要件チェックリスト

1. [critical] A・D・H は既存の合意で進み、形式的なインタビューや再承認を追加しない。B は年齢不明の扱いをユーザーに確認する。
2. [critical] C・D は不要な委譲を起動しない。J は独立範囲を分担可能と判断し、全文履歴ではなく担当範囲・根拠・必要な参照先を渡す。
3. [critical] E は全 UI review suite を強制しない。F は要求された accessibility / responsive を静的・実画面の証拠で確認し、編集はしない。
4. [critical] I のユーザーが明示した最終確認は守る。K は状態質問に答えて承認済み作業を継続し、merge の承認へ拡張しない。
5. L は利用できない Claude provider を要求せず、読める plan は参照先で渡す。
6. G は制約に沿った比較・推奨・不確実性を示し、固定の案数・点数・複数 agent を必須にしない。

## subagent 投入プロンプト

対象の repo 内 SKILL.md と指定ケースだけを fresh agent に渡す。次の具体的な行動・質問・委譲・使う skill を実演させ、不明瞭点・裁量補完・再試行を報告させる。評価側はケースごとに上の契約と照合する。これは指示選択のシミュレーションであり、本番 repo 編集・外部操作・実 runtime 性能測定は含まない。

## 最終実行結果

`docs/harness-review-2026-09-19.md` の追加検証を参照。tool 数・duration が取得できない場合は数値収束を主張しない。
