---
name: ai-usage-report
description: "AI の利用実態をログから棚卸しして、社内申請・月次報告・契約見直しの根拠を作る。何にどのエージェントを使い、どのモデルが枠制約で使えなくなっているかを実測で出す。「AI利用申請」「利用実態」「月次報告」「どのモデル使ってる」で起動。"
---

# ai-usage-report

「AI をどれだけ使っているか」を感覚ではなくログから出す。用途は社内申請、月次の利用報告、プラン変更の判断。

設定改善が目的なら `config-tune`（同じ cclens を使うが出力先が違う）。こちらは**対人説明のための実態把握**で、設定は変更しない。

## 前提

- Claude Code: `cclens`（`brew install lambdalisue/cclens/cclens`）と `~/.claude/projects/*/*.jsonl`
- Codex: `~/.codex/{sessions,archived_sessions}/**/rollout-*.jsonl`
- pi / omp: `~/.pi/agent/sessions/`, `~/.omp/agent/sessions/` の `<encoded-cwd>/<ISO>_<uuid>.jsonl`
- issue tracker: Linear MCP 等

無いランタイムは飛ばす。全部揃わなくても部分集計で報告は書ける。

## 集計器を選ぶ

複数 runtime または Codex / OpenCode / pi の実測は、利用可能なら `cclens-multi` を先に使う。PATH に無ければ既知の checkout の導入記録から実行ファイルを探す。手順・欠損の扱い・委譲分析は [config-tune](../config-tune/SKILL.md) の Phase 0–1 に従い、ここでは設定を変更しない。以下の runtime 別手順は `cclens-multi` が利用できない場合、またはその出力にない指標が必要な場合だけ使う。

## Phase 1: Claude Code の実測

このスキルのディレクトリを起点にヘルパーを解決する（cwd のプロジェクトではない）。

```bash
cclens analyze
python3 <skill-dir>/scripts/sessions.py --since <YYYY-MM-DD> --repos <repo1>,<repo2>
```

`sessions.py` は hook が自動起動したセッションを落として、人が始めたセッションだけを repo別・作業種別・月別に数える。**cclens のセッション数をそのまま報告に使わない**。security-review 系の hook を入れていると自動セッションが3〜4割を占めることがあり、作業量を大きく見せてしまう。

日付は `--tz`（既定 `Asia/Tokyo`）でローカル日付に変換してから集計する。ログの timestamp は UTC なので、変換しないと月末・月初のセッションが隣の月に落ちる。

repo を跨いだ集計やトークン量は cclens SQL で取る:

```bash
cclens sql "SELECT substr(started_at,1,7) m, model, count(*) n FROM events
            WHERE model IS NOT NULL GROUP BY 1,2 ORDER BY m DESC"
cclens sql "SELECT agent, count(*) runs, sum(out_tokens) FROM subagent_runs
            GROUP BY 1 ORDER BY runs DESC LIMIT 20"
cclens sql "SELECT surface_id, count(*) n FROM events
            WHERE surface_kind='skill' GROUP BY 1 ORDER BY n DESC LIMIT 25"
```

スキーマは `SELECT sql FROM sqlite_master`。

## Phase 2: 他ランタイム（Codex / pi / omp / OpenCode）の実測

Codex, pi / omp, OpenCode の実測手順、抽出用コマンド、および SQL は [runtime-metrics-collection](references/runtime-metrics-collection.md) を参照。

## Phase 3: 成果側（issue tracker）

完了タスクを取るが、**件数をそのまま成果にしない**。issue tracker の完了件数は粒度がバラバラで、実態と乖離する。

取ったら必ず次を分けて数える:

- QA トリアージ・UI 微修正など、1件が数十分で終わるもの
- CI やボットが自動起票したもの（人の作業ではない）
- estimate が入っているもの（入っていない方が多いのが普通）

そのうえで「意味のある塊」をフェーズ単位で数え直す。件数ではなくこちらを報告に使う。

## Phase 5: 報告を書く

構成は次の4つ。

1. **何に時間を使っているか**: repo別と作業種別。実装より PR 周辺・CI 対応が多いなら、そう書く（盛らない）
2. **どのエージェントをどう使い分けているか**: skill 起動回数と subagent の内訳。役割分担が固定しているならその形
3. **枠制約が実際に何を奪ったか**: モデル構成の月次推移。上位モデルの比率が落ちていれば、何の用途が落ちたかを本人の使い分けと突き合わせて書く。これが申請で一番効く
4. **成果**: フェーズ単位の塊と、紐づく PR / issue

### 報告に使ってはいけない数字

これらは水増しになるので根拠にしない。理由も添えて除外を明示する。

- **セッション数（cclens のまま）**: hook 自動起動を含む
- **Codex のログファイル数**: subagent と自動レビューを含む（Phase 2）
- **完了タスク件数**: 粒度が揃わない。自動起票も混ざる
- **セッションの経過時間**: 放置時間を含む
- **ツールが表示する「削減時間」の推定値**: 実測ではない

## Phase 6: 記録

次回同じ集計を回して比較できるよう、集計日・期間・出した数字を `~/.claude/memory/ai-usage-<YYYY-MM>.md` に残す。次回は差分だけ見ればよくなる。
