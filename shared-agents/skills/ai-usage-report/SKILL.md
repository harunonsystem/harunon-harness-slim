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
- pi: `~/.pi/agent/sessions/<encoded-cwd>/<ISO>_<uuid>.jsonl`
- issue tracker: Linear MCP 等

無いランタイムは飛ばす。全部揃わなくても部分集計で報告は書ける。

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

## Phase 2: Codex の実測

**`scripts/codex-usage.py`（harness repo）を使う。rollout ログを自前で数え直さない。**

```bash
python3 <harness-repo>/scripts/codex-usage.py --since <YYYY-MM-DD>
```

ファイル数を `find | wc -l` で数える方式は3つの理由で実態とずれる。このスクリプトは3つとも処理済み:

- `archived_sessions/` に移された過去のログが落ちる（重いセッションほど古いので「最近は軽い」と読み違える）
- 1ファイル＝1セッションだが、`thread_source` が `user` / `subagent` / `guardian_review` で混ざる。**人が始めた Codex セッションは `user` の行だけ**
- `"model":"..."` を grep で数えると、セッション数ではなく turn_context の出現回数（≒ターン数の代理）になる

出力の `thread_source 別` と `model × effort 別` が報告に使う部分。月次の推移が要るなら `--since` を変えて月ごとに実行して並べる。

## Phase 3: pi の実測

pi は Codex と保存形式が違う。ファイル名の先頭が ISO 日付、モデルは `model_change` イベントの `modelId`。

```bash
# 月別セッション数
find ~/.pi/agent/sessions -name '*.jsonl' | perl -ne 'print "$1\n" if m{/(\d{4}-\d{2})}' | sort | uniq -c

# モデル構成（1セッション内で複数回切り替わるので、セッション数ではなく切替回数）
find ~/.pi/agent/sessions -name '*.jsonl' \
  | xargs perl -ne 'print "$1\n" if /"type":"model_change".*"modelId":"([^"]+)"/' \
  | sort | uniq -c | sort -rn
```

`~/.pi/agent` 直下には `observability/history.jsonl` などセッションでない JSONL があるので、`sessions/` 配下に限定する。

## Phase 4: 成果側（issue tracker）

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
