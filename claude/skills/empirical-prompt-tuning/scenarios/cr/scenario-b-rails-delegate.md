# cr / シナリオ B（edge: Rails プロジェクト → /self-review 委譲）

## 対象

`~/.claude/skills/cr/SKILL.md`

## 状況設定

プロジェクトルートに `Gemfile` と `app/controllers/` が存在する（と仮定して扱う。実ファイル確認は不要）。ユーザーが `/cr` を実行した。ローカル変更は `app/controllers/users_controller.rb` の修正 1 件。

## 要件チェックリスト

1. [critical] Rails プロジェクトと判定し、/self-review に委譲する。cr の Step 1 以降を実行しない
2. 委譲することをユーザー向け出力に明示する
3. TS 向けの Code Review Report を生成しない

## subagent 投入プロンプト

```
あなたは ~/.claude/skills/cr/SKILL.md を白紙で読む実行者です。

## 対象プロンプト
~/.claude/skills/cr/SKILL.md を Read で読んでください。

## シナリオ
（↑ の状況設定を貼る）

## 要件チェックリスト
（↑ の 3 項目を貼る）

## タスク
1. 対象プロンプトに従ってこのシナリオでの動作を実行する（委譲先の /self-review 本体まで実行する必要はない）。
2. レポート構造（成果物 / 要件達成 ○×部分的 / 不明瞭点 / 裁量補完 / 再試行）で返答する。

全体 300 語以内。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |
| 2026-07-11 iter1 | ○ | 100% | 全達成 | 委譲成功。不明瞭点: 委譲の実行手段（Skill 起動か案内のみか）が未規定 → Step 0 に委譲手順を明文化 |
