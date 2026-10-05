---
description: Issue の spec 整理・分割で tracker をどう使うか。spec を整える skill（to-spec / to-tickets / spec-ready / wayfinder）を使う前に明示 Read する。
paths:
  - "**/issue-tracker.md"
---

# Issue tracker

agent のワークフローは、チームで共有する tracker（Linear など）を使っていても、他のメンバーの運用を変える書き込みをしない。ラベルや状態はチームの運用の一部で、agent の都合で増やしたり動かしたりすると他の人の画面と集計が変わる。matt 系 skill が「issue tracker が提供されているはず」と言うときの tracker はこの文書を指す。

## 書いてよいもの

- 元 Issue の sub-issue を作る。1 枚 = 1 本の振る舞い（tracer bullet）。本文は What to build / Acceptance criteria / Blocked by を持つ
- sub-issue 同士の blocked by リンク
- spec を tracker に残すなら、元 Issue の sub-issue か、元 Issue へのコメントにする（残すかどうかは skill の手順に従う）
- 部分的に止まったときの記録は、元 Issue へのコメント

## 書かないもの

- ラベル（`ready-for-agent` などの triage label を含む）の追加・新設
- Issue の状態変更、アサイン先の変更
- 元 Issue の本文の書き換え
- repo の `CLAUDE.md` / `AGENTS.md` への tracker 設定の追記（`setup-matt-pocock-skills` を共有 repo で実行しない）

ラベルや状態に依存する skill はこの方針と両立しない。`triage` はチームの tracker に使わない。`wayfinder` は map と ticket をラベルで管理するので、tracker はローカル markdown（`.scratch/<feature>/`。`.git/info/exclude` で除外し、共有の `.gitignore` は変えない）にする。

## 着手できる状態

ラベルを使わないので、実装に入れるかは本文で判定する。目的、受入条件、範囲外が本文・会話・repo から確定でき、Blocked by が全部完了していれば着手できる。

## 複数 repo にまたがる振る舞い

repo が分かれていることは、sub-issue を分ける理由にならない。1 枚の sub-issue に対して、触る repo ごとに PR を出す。PR は契約（schema）→ 実装（API）→ 利用側（front）の順に出す。生成物が衝突するなど並行できない振る舞い同士は、sub-issue の blocked by で順番を決める。
