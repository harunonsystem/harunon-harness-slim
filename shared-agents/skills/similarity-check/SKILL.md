---
name: similarity-check
description: "AST ベースの重複コード検出（mizchi/similarity）。リファクタ前の重複洗い出し、レビュー・pre-review-check の DRY 検査、新規実装前の copy-from-existing 探しに使う。「重複コード検出」「similarity」「似たコード探して」で起動。"
---

# similarity-check

mizchi/similarity の CLI 群でコードベースの意味的重複（テキスト一致ではなく AST 比較）を検出する。

## ツール選択

| 対象言語 | コマンド | 成熟度 |
| --- | --- | --- |
| TypeScript / JavaScript | `similarity-ts` | Production Ready |
| Python | `similarity-py` | Beta（結果は要確認） |

未インストールなら `cargo install similarity-ts similarity-py` を案内する。

## 基本コマンド

```bash
similarity-ts .                  # カレント以下をスキャン
similarity-ts src/a.ts src/b.ts  # 特定ファイル間
similarity-ts . --print          # 実コードも表示
similarity-ts -h                 # threshold 等の詳細オプション
```

出力例: `src/utils.ts:10-20 calculateTotal <-> src/helpers.ts:5-15 computeSum / Similarity: 92.50%`

## 使いどころ

1. **リファクタ前の重複洗い出し**: スキャン → 重複ペアを影響度順に整理 → 統合プランを提示。統合先の妥当性判定は `rules/review-policy.md` の DRY 基準に委譲する
2. **レビュー / pre-review-check の補助**: 変更ファイルを対象に実行し、`rules/core-standards.md`「コーディング基準」の禁止事項『コピペパターン』の機械的裏付けにする
3. **新規実装前**: Copy-from-existing 原則のコピー元探しに、書こうとしている処理と似た既存実装を探す

## 解釈の規律

- デフォルトしきい値（`--threshold` 未指定時）: 90%+ は統合候補、80-90% は要文脈判断、それ未満は基本ノイズ。コードベースの語彙・テスト比率で変わるため `--threshold N` で調整する
- 検出結果は leads であって facts ではない。統合提案の前に必ず両方のコードを開いて意図的な分離でないか確認する
- テストコードの類似の扱いは `rules/review-policy.md`「テストファイルのサイズと重複の扱い」節に委譲する
