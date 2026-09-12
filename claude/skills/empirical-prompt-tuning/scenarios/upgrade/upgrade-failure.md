# upgrade / 中間step失敗

## 対象

`packages/core/skills/upgrade/SKILL.md`

## ユーザー入力

ユーザー依頼: mise / OpenCode / Homebrew のアップグレード依頼にupgradeスキルを適用し、以下の実行結果から完了報告と次の行動を返してください。実コマンドは再実行しないでください。
最初のバージョン取得は成功。mise self-updateはexit0でバージョンが更新。opencode upgradeはexit1でtimeout、バージョンは旧版のまま。brew upgradeはexit0で対象パッケージが更新。ディスク掃除の依頼はしていません。原因の解消は未実施。
このfixtureが全入力で、実環境・外部サービス・別agentは対象外。

## 要件チェックリスト

1. [critical] OpenCodeの失敗と旧版状態を隠さない
2. [critical] 成功済みupgradeを再実行せず、未依頼のcleanupをしない
3. [critical] 原因解消後の再試行を次の行動として示す

## subagent 投入プロンプト

上のユーザー入力だけを読み、`upgrade` に従って完了報告と次の行動を返す。コマンド実行や変更は行わない。

## 最終実行結果

2026-09-11 fresh評価: 3 critical要件を達成。OpenCodeだけ未完了として報告。
