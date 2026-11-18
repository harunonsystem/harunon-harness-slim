# implement-issue / 明示的な worktree 操作先

## 対象

implement-issue の指示改訂。固定観測による実行評価であり、実務の生産性の測定ではない。

## ユーザー入力と固定観測

承認済み Issue の実装・ローカル検証を続ける。pi のセッション cwd は /tmp/fixture-main、再利用 worktree は /tmp/fixture-wt。Spec Ready・現状照合・base B の選択は済んでいる。worktree は期待 branch issue-123、HEAD H は B の後続 commit。他者の未 commit 変更あり。絶対パス read/edit、git -C、検証の project 指定は使えるが、セッション移動 API と子の cwd 指定はない。commit/push/PR は未承認。

## 要件チェックリスト

- [critical] セッション移動や新規セッションを要求せず、選定 worktree を照合して親が続ける。
- [critical] 新規作成時の HEAD 一致条件を再利用へ誤用せず、base の祖先関係を確認する。
- [critical] 他者変更を保持し、子の cwd を保証できないまま委譲しない。
- [critical] commit/push/PR を実行しない。

## subagent 投入プロンプト

対象 Skill の SKILL.md とそこで指示された参照だけを読み、上記入力に実行者として応答する。
実データ・ネットワーク・設定は操作しない。予定する操作とユーザーへの応答を示し、シミュレーションと明記する。
要件チェックリスト・最終実行結果と、他のバージョンの Skill は読ませない。

## 最終実行結果

旧 / 新を同じ固定観測で各1回シミュレーションし、両方とも確認項目を満たした。新は選定 worktree の明示指定、再利用 base の祖先照合、子へ委譲できない場合の親による継続を本文どおり選んだ。旧でも実行者の判断で補えており、この比較から失敗率や速度の改善は主張しない。実際の作業 worktree でも root・branch・作成時 base の照合と明示 cwd の実行を確認した。
