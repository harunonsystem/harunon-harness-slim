---
name: config-tune
description: "cclens と /insights の実測で Claude Code 設定を定期改善する。harness 環境は packages/core（SSOT）、非 harness は ~/.claude へ反映。「config-tune」「設定の健康診断」で起動。"
---

# config-tune

cclens（定量分析）と Claude ネイティブ `/insights`（定性の修正シグナル）の結果を、設定改善のサイクルに変換する。分析自体は各ツールの仕事。この skill は「収集 → 分類 → 反映先へのルーティング → 適用 → 記録 → 検証」を担う。

旧 harness 製 insights skill（ログ分析エンジン）は Claude ネイティブ `/insights` への一本化で退役済み。再 vendor しない（`test_retired_harness_skills.py` の契約）。ここでは分析器を持たず、出力の消費側だけを定義する。

## 起動タイミング

- 手動 `/config-tune`、または「設定を改善して」「最近同じところで引っかかる」系の依頼
- 目安は月1回、または同じ失敗・修正指示が続いたと感じたとき
- SessionEnd hook 等での自動実行はしない（過去に不採用と決定済み。plans/README）

## Phase 0: 環境判定

1. **cclens の有無**: `command -v cclens`。無ければ `brew install lambdalisue/cclens/cclens` を案内する。導入しない場合は insights-only モードで進める（強制しない）
2. **harness repo の有無**: `packages/core/lessons/lessons.json` と `scripts/distribute.py` を持つ checkout を特定できるか（cwd がその repo でなくてもパスが分かればよい）。特定できれば **harness mode**、できなければ **standalone mode**

## Phase 1: Collect

cclens がある場合はまず store を更新し、主要レポートを取る:

```bash
cclens analyze                  # store 更新（各レポートも自動で走るが明示しておく）
cclens doctor                   # 優先度サマリ。ここから始める
cclens failures --scope global  # 繰り返し失敗（hook block / path typo / edit precondition 等）
cclens waste --scope global     # 未使用・常駐で重い設定
cclens stuck                    # 再編集バーストで停滞したファイル
cclens overhead                 # セッション開始時の常駐コスト
cclens prompts                  # steering / correction の比率
```

固定レポートで拾えない疑問は `cclens sql`（read-only。`SELECT sql FROM sqlite_master` でスキーマ確認）で store に直接問い合わせる。

insights 側: ユーザーが直近 `/insights` を実行済みなら結果を取り込む。未実行なら実行を促す。得られない場合は `~/.claude/projects/*/memory/*.md`（ユーザーが明示記録した教訓。ログ推測より信頼度が高い）だけ読んで進める。

## Phase 2: Classify

各 finding を3分類する:

- **live hygiene**: 個人の使い方の歪み。未使用のまま残る skill、常駐で重い文書、繰り返し手動で通している操作 → live 設定の掃除
- **generalizable**: 別プロジェクトでも再発し得る失敗・修正パターンで、rule / hook / skill / 常駐文書で防げる → 設定資産への昇格候補
- **project-specific**: 特定プロジェクトのパスや規約に依存 → そのプロジェクトの CLAUDE.md（harness mode では extras 側の rules）

判断軸は「この教訓はこのプロジェクトを離れても再発するか」。迷ったらユーザーに聞く。抽象教訓（「ちゃんとやる」系）はそのまま記録せず、1行で具体的・実行可能な形に落としてから扱う。

## Phase 3: Route & Apply

findings の一覧を提示し、利用中のエージェントのユーザー確認機能で適用可否を1件ずつ取る。findings の質はまちまちなので一括承認はしない。

### harness mode（SSOT-first）

- 書き込み先は harness repo の `packages/core/` 側。`~/.claude` 等の live 側は直接編集しない（次の配布で無言で巻き戻る）
- 行き先の目安:
  - コーディング規約・AI 振る舞い・失敗教訓 → `rules/core-standards.md` の該当節
  - レビュー基準 → `rules/review-policy.md`
  - ワークフロー・skill ルーティング → `CLAUDE.md`
  - 機械的ガード（繰り返し block されている操作） → `hooks/` + `policy/danger-rules.json`
  - プロジェクト固有 → extras 側（会社・プロジェクト固有を置く private submodule）の `rules/`
- 書き込み前に既存内容と照合し、重複は「記載済み」でスキップ、矛盾は両方を提示して解決方針を確認する
- 適用後は `"$(mise which python3)" scripts/validate-harness.py` を通し、配布は `/sync-settings`（`distribute.py <target> --push`）で行う

### standalone mode

- 書き込み先は `~/.claude/` 直接（CLAUDE.md、settings.json、skills/）
- 包括的な対話チューニングが目的なら `cclens optimize`（分析済みデータを積んだ interactive claude セッション）を代替導線として案内してもよい

## Phase 4: Record

- harness mode: `packages/core/lessons/lessons.json` に `status: "pending"` で追記（スキーマは `packages/core/lessons/README.md`。validator が 30 日以上の pending を警告する）
- standalone mode: `~/.claude/memory/<topic>.md` に先頭 1 行サマリ付きで記録する

## Phase 5: Verify（次回以降のループ）

- 次の `cclens doctor` で対象 finding が消えたか確認する。残っていれば同じ修正を繰り返さずアプローチを変える
- 記録した lessons / memory の status を実測に合わせて更新する（直ったら enforced、効かなかったら別の enforced_by へ）
