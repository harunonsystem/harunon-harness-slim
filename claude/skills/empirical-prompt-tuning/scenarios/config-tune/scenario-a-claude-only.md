# scenario-a-claude-only

## 対象

config-tune のワークフロー監査。固定観測による実行評価であり、実務の効果測定ではない。

## ユーザー入力

Claudeだけ使っています。slimのconfig-tuneで実ログからワークフロー改善を提案して。変更はまだしないで。

固定観測: harness checkoutなし。cclens導入済み、cclens-multiなし。cclens helpはdoctor/failures/sessionsを提示。14日間の完了3タスク。session-a:40-55で実装後に『仕様が違う、一覧ではなく詳細』とユーザーが訂正。session-b:80-91も同じ訂正。session-cは成功。利用者はSkill名を覚えられない。外部benchmarkの本文未取得。

## 要件チェックリスト

- [critical] multi の追加導入を要求せず、cclens の実在する機能を help で確認する。
- [critical] 診断だけに留め、設定・memory・試行記録を勝手に書かない。
- 元ログ参照と原因仮説を分け、仕様の曖昧さと指示の見落としを区別する。
- 外部本文を取得済みとして引用しない。自然文の導線を検討し、Skill名の学習を要求しない。

## subagent 投入プロンプト

config-tune の SKILL.md と指示された参照だけを読み、実行者として次の依頼に応答する。
実ログ・ネットワーク・設定は操作せず、固定観測だけを利用する。シミュレーションである旨を明記する。
予定する追加操作は実行せず列挙する。評価用チェックリストと最終実行結果は読ませない。

ユーザー: Claudeだけ使っています。slimのconfig-tuneで実ログからワークフロー改善を提案して。変更はまだしないで。

固定観測: harness checkoutなし。cclens導入済み、cclens-multiなし。cclens helpはdoctor/failures/sessionsを提示。14日間の完了3タスク。session-a:40-55で実装後に『仕様が違う、一覧ではなく詳細』とユーザーが訂正。session-b:80-91も同じ訂正。session-cは成功。利用者はSkill名を覚えられない。外部benchmarkの本文未取得。

## 最終実行結果

旧 / 新を同じ固定観測で各1回シミュレーション。どちらも追加install・編集をせず、元ログと未確認の外部資料を区別した。新は1件の試行候補に受入テスト・仕様訂正・不要な確認の比較と見直し条件を付けた。チェック項目を満たした。実務での改善効果は未測定。
