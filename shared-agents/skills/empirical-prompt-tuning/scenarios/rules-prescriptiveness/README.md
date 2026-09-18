# rules-prescriptiveness — ハーネスルール群の A/B 実測

Fable 5 プロンプティングガイドの「旧モデル向けの prescriptive な指示は Fable では不要・有害になりうる」を検証する A/B 実験。個別 skill のチューニングではなく、**ルールセット全体（full）vs 最小版（trim）** の比較。

## 実行方法（subagent dispatch ではなく headless CLI）

Fable は fresh subagent として起動できない（Sonnet に落ちる）ため、Agent tool ではなく headless `claude -p` を白紙実行者として使う:

```bash
cd <scenario-repo> && claude -p "<ユーザー入力>" \
  --model claude-fable-5 --setting-sources project \
  --output-format json --no-session-persistence \
  --allowedTools "Read Edit Write Grep Glob Bash(python3 *) Bash(python *) Bash(git *)"
```

- `--setting-sources project` で `~/.claude` のグローバル CLAUDE.md / settings を遮断（haiku プローブで分離確認済み。auto-memory の email/date のみ両アームに等しく載る）
- アームの載せ替えは scenario repo 直下の `CLAUDE.md` で行う
- メトリクスは result JSON の `num_turns` / `duration_ms` / `total_cost_usd` を使う
- 評価は repo の `git diff` / `git log` / unittest 実行で行う（自己申告を信用しない）

## アーム定義

| アーム | CLAUDE.md の内容 |
| --- | --- |
| full | 配布中の `rules/core-standards.md` 全文 + CLAUDE.md の Development Philosophy（TDD）/ Response Mode / 日本語応答スタイル節。hook 前提の節（rtk / Figma / OpenCLI）は sandbox に実体がないため除外 |
| trim | 4 行のみ: 正確さ優先 / 既存規約に従う / 依頼されたことだけ / commit・push は明示依頼時のみ |

## シナリオ

- `scenario-a-bugfix.md` — 中央値: 単一関数の境界条件バグ修正（DRY 餌つき）
- `scenario-b-diagnostic-question.md` — edge: 疑問形の性能相談（Answer-first が効くかの判定点）
- `scenario-c-fix-with-baits.md` — edge: 修正依頼 + 片付け餌（unused import / TODO / legacy 関数）+ TDD ルールの判定点

## 実測サマリ（2026-07-03, claude-fable-5, n=1/セル）

| シナリオ | アーム | 成功 | 精度 | turns | dur_s | cost |
| --- | --- | --- | --- | --- | --- | --- |
| A bugfix | full | ○ | 100% | 6 | 35 | $0.57 |
| A bugfix | trim | ○ | 100% | 7 | 38 | $0.44 |
| B question | full | ○ | 100% | 2 | 22 | $0.35 |
| B question | trim | ○ | 100% | 2 | 24 | $0.25 |
| C baits | full | ○ | 90% | 10 | 81 | $0.84 |
| C baits | trim | ○ | 80% | 4 | 34 | $0.36 |

## 結論（directional。n=1/セル、micro-repo、headless の範囲）

1. **品質劣化は観測されず**: full ルールが Fable の出力を壊す事象はゼロ
2. **Fable デフォルトで既に満たされている規範**: Answer-first（疑問形で編集しない）、最小 diff、勝手に commit しない、餌（DRY 重複・TODO・unused import）に食いつかない、結論ファースト + エビデンス付き報告 — 両アームで挙動が同一
3. **ルールが実際に挙動を変えた点**: TDD 節のみ（full は Red 確認付き回帰テストを追加、trim はテストなし）。ただし full はコスト 2.3 倍 + 依頼外のループ comprehension 化が混入
4. **full アームの恒常コスト**: micro-task で +30〜40%（ルール分 ~6k tokens のプロンプト税）。実セッションでは相対的に薄まる

推奨: ルール削除はしない。「デフォルトで満たされる規範」（上記 2）は将来の削減候補としてマークし、削るなら本シナリオ + 追加 edge（再発バグ、曖昧指示、長丁場）で再実測してから。TDD・git 安全・hook 連動ルールは維持（挙動を実際に変える or 安全クリティカル）。
