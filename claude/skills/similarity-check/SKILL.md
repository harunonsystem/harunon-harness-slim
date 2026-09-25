---
name: similarity-check
description: "mizchi/similarity による重複検出。差分の言語に応じた並列検査、リファクタ前の洗い出し、レビュー・pre-review-check の DRY 検査、新規実装前のコピー元探しに使う。「重複コード検出」「similarity」「似たコード探して」で起動。"
user-invocable: true
argument-hint: "[path] [--threshold 0.85]"
---

# similarity-check

mizchi/similarity の言語別 CLI でコードベースの構造的な重複を検出する。

## ツール選択

| 対象言語 | コマンド | 成熟度 |
| --- | --- | --- |
| TypeScript / JavaScript（`.ts`, `.tsx`, `.js`, `.jsx`, `.mts`, `.cts`, `.mjs`, `.cjs`） | `similarity-ts` | Production Ready |
| Python（`.py`） | `similarity-py` | Beta |
| Rust（`.rs`） | `similarity-rs` | Beta |
| CSS（`.css`） | `similarity-css` | Experimental |
| SCSS（`.scss`） | `similarity-css --scss` | Experimental |
| Markdown（`.md`, `.markdown`） | `similarity-md` | Experimental |
| Elixir（`.ex`, `.exs`） | `similarity-elixir` | Experimental |

## 対象と実行

1. 明示されたファイル・ディレクトリ、またはレビュー元が選んだ差分を使う。指定がないローカル作業では `git diff --name-only --diff-filter=ACMR -z HEAD` と `git ls-files --others --exclude-standard -z` から変更ファイルを集める。差分がなければ対象ディレクトリ内のファイルから選ぶ。
2. 拡張子を上表のコマンドに対応付け、同じコマンドとオプションの組は 1 回だけ起動する。CSS と SCSS は別ジョブにする。対応拡張子がなければ検査対象なしと報告する。
3. 差分起点でも変更ファイルだけを CLI に渡さず、比較相手を含む関連ディレクトリ（通常は同じ package / リポジトリ）をスキャンする。明示的なファイル間比較なら、そのファイルを渡す。
4. 言語ごとの独立した CLI を並列実行して全結果を回収する。未インストールの実行ファイルはその言語だけ保留し、`cargo install <実行ファイル名>`（SCSS も `similarity-css`）を案内して他の検査を続ける。
5. 差分レビューでは、少なくとも片側が変更ファイルにあるペアを優先し、該当箇所が変更されたか確認して報告する。

## 基本コマンド

```bash
similarity-ts .                  # 対象ディレクトリの TS / JS をスキャン
similarity-rs .                  # Rust の変更がある場合
similarity-css .                 # CSS の変更がある場合
similarity-css --scss .          # SCSS の変更がある場合
similarity-md .                  # Markdown の変更がある場合
similarity-elixir .              # Elixir の変更がある場合
similarity-ts src/a.ts src/b.ts  # 明示的なファイル間比較
```

出力例: `src/utils.ts:10-20 calculateTotal <-> src/helpers.ts:5-15 computeSum / Similarity: 92.50%`

## 使いどころ

1. **リファクタ前の重複洗い出し**: スキャン → 重複ペアを影響度順に整理 → 統合プランを提示。統合先の妥当性判定は `rules/review-policy.md` の DRY 基準に委譲する
2. **レビュー / pre-review-check の補助**: 変更ファイルと関連実装の類似を確認し、`rules/core-standards.md`「実装の梯子」2 段目（既存コードの再利用）の機械的裏付けにする
3. **新規実装前**: Copy-from-existing 原則のコピー元探しに、書こうとしている処理と似た既存実装を探す

## 解釈の規律

- しきい値は CLI ごとのデフォルトを使う。調整時の `--threshold` は `0.0`〜`1.0`（例: `0.9`）で指定する。90%+ は統合候補、80〜90% は要文脈判断、それ未満は基本ノイズ
- 検出結果は leads であって facts ではない。統合提案の前に必ず両方のコードを開いて意図的な分離でないか確認する
- Beta / Experimental の結果は誤検出を前提に原文で確認し、未検出を「重複なし」の証拠にしない
- テストコードの類似の扱いは `rules/review-policy.md`「テストファイルのサイズと重複の扱い」節に委譲する
