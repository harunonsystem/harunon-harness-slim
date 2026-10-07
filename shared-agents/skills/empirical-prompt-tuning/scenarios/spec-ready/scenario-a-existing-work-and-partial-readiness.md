# spec-ready / 既存作業と slice ごとの READY 判定

## 対象

`packages/core/skills/spec-ready/SKILL.md`

## ユーザー入力

親 Issue PARENT-101 は一覧画面の再構成を求めている。現行の表示・操作を維持する構造整理は前後の E2E が 6/6 で通る。新 API への切替は pagination / search / count / image URL の契約がまだ一致せず、依存先の確認が必要。同じ機能の空の未割当 backlog Issue PARENT-102 がある一方、別チームの WORK-42 と backend PR #73、schema PR #24 に実装が進んでいる。ユーザーは「既存動作を合わせ、望ましくない旧動作の改善は分けて spec-ready にして」と依頼した。tracker と repo は閲覧でき、tracker への書き込みは `rules/issue-tracker.md` の範囲に限る。

## 要件チェックリスト

1. [critical] 親に紐付かない WORK-42 と PR #73・#24 の担当・実装範囲を確認し、同じ slice の子 Issue を重複作成しない
2. [critical] 既存動作を保つ構造整理と新 API 切替の受け入れ条件を分け、独立する前者は READY にできる
3. [critical] 契約不一致が残る新 API 切替は READY にせず、確認すべき契約と次の行動を記録する
4. [critical] 最終報告と親へのコメントで、READY / pending 各 slice に behavior・migration・release boundary を対応付けて記録し、一方の方針を他方に取り違えさせない
5. [critical] 親全体の BLOCKED を理由に独立した READY slice の公開を止めない
6. 望ましくない旧動作の改善を構造整理の互換性条件へ混ぜない
7. ラベル・状態・親 Issue 本文を変更せず、結論と未確定事項を短く伝える

## subagent 投入プロンプト

```
あなたは指示文書を白紙で読む実行者です。今回の会話の経緯は知りません。

## 対象プロンプト
packages/core/skills/spec-ready/SKILL.md を読んでください。参照先の rule や skill が必要なら、同じ repo の packages/core/ 配下を読んでください。

## シナリオ
<「ユーザー入力」節だけをここに貼る>

## タスク
この情報を起点に、追加で調べるもの、slice ごとの READY 判断、作成・再利用する Issue、親への記録、短い最終報告を示してください。実際の tracker 書き込みや model 委譲は行わないでください。

## レポート構造
- 成果物: 初動と想定する最終結果
- 不明瞭点: 指示文書で解釈に迷った箇所
- 裁量補完: 指示で決まっておらず自分で埋めた箇所
- 再試行: 同じ判断をやり直した回数と理由
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |

モデル実行評価は未実施。静的なシナリオ確認を合格実測として記入しない。
