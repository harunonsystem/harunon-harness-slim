---
name: simplify
description: 実装後の差分を、観測可能な挙動を変えずに簡素化する。不要な抽象・重複・分岐・古いコードや資料を減らし、project規約に沿った読みやすい形へ整理するときに使う。
compatibility: codex opencode pi omp claude
---

# Simplify

最近変更した差分を、**挙動を保ったまま**読みやすく・小さく・一貫した構造へ整理する。
対象は原則として今回触ったコードと、その変更によって不要になったコード・テスト・資料に限定する。再設計や仕様変更はこの skill の仕事ではない。

この workflow は Anthropic Claude Code の `code-simplifier` が重視する「preserve functionality / clarity over brevity / recent changes only」を portable な形へ落としたもの。runtime 固有の subagent 数・model・slash command には依存しない。

## 原則

1. **挙動を変えない**: return value、例外、外部副作用、公開契約、許容入力を変える提案は simplification ではない。必要なら別変更として報告する。
2. **短さより明瞭さ**: 行数削減を目的にしない。dense one-liner、nested ternary、過剰な共通化より、一読で理解できる明示的なコードを優先する。
3. **project規約を優先する**: `AGENTS.md` / `CLAUDE.md` / rules / 近傍の既存実装を generic な好みより優先する。
4. **一つの正本に寄せる**: 同じ役割の old/new path、fallback、互換 shim、重複 helper を並存させない。互換性要件が明示されているものは消さない。
5. **テストを増やすことを成果にしない**: simplification 自体のために実装詳細テストを追加しない。テストを変更する必要がある場合は `test-audit` を適用する。
6. **今回の差分から広げない**: 近傍に別の問題を見つけても、今回の変更が不要化したもの以外は勝手に直さない。

## 1. 対象差分を確定する

ユーザー指定の diff / branch / PR があればそれを優先する。指定がなければ現在の作業差分を対象にする。

- `git status --short` で untracked を含める。
- tracked file は適切な base からの diff を読む。base の導出は repository の review policy に従う。
- 今回変更したファイルだけでなく、変更によって obsolete になり得る呼び出し元・helper・test・docs を `rg` で確認する。
- optional focus が渡された場合は、その観点を優先するが原則は上書きしない。

差分が数行の一意な修正なら、儀式的な多段レビューを作らず一回の確認で終える。

## 2. 四つの観点で削れるものを探す

### Reuse

新しい helper・型・分岐を書く前に、同じ責務の既存実装を wider codebase から探す。ただし trivial な式を helper 化するなど、再利用のために理解コストを増やさない。

### Clarity

不要な nesting、redundant state、parameter sprawl、copy-paste、stringly-typed な分岐、説明的すぎるコメント、単一用途の早すぎる abstraction を減らす。複数 concern を一関数へ押し込む「短縮」はしない。

### Efficiency

同じ値の再計算、重複 I/O、N+1、明らかな hot-path の不要処理など、差分から根拠を示せる無駄だけを除く。premature optimization はしない。

### Cleanup

今回の変更で不要になった old path、fallback、deprecated shim、dead code、重複 test、古い資料・コメントを削除または更新する。削除前に利用箇所を検索し、「見つからない」を一箇所の観測だけで断定しない。

## 3. 変更する

候補ごとに原則へ照らし、挙動保持を証明できない変更は適用しない。同じ箇所に複数案がある場合は project 規約 → 挙動保持 → 明瞭さの順で選ぶ。それでも同等なら無理に変更しない。

編集は逐次行い、前の編集で前提が変わった候補は再確認する。最終形が「元の実装 + 新実装 + adapter」の三層になっていたら、本当に互換性要件があるか確認し、不要なら canonical path 一つへ畳む。

## 4. 検証する

変更前に green だった関連 test を変えずに再実行することを基本とする。repository が宣言する typecheck / lint / test / build のうち、今回の差分に必要な deterministic checks を実行する。

最後にもう一度 diff を読み、次を確認する。

- 受入条件と観測可能な挙動が変わっていない。
- 不要になった code / test / docs / compatibility layer が残っていない。
- 新しい abstraction や fallback を simplification の名目で増やしていない。
- 読みやすさが改善していない変更は戻す。

## 5. 報告する

適用した simplification、意図的に適用しなかった behavior-changing proposal、実行した検証だけを短く報告する。変更が不要なら「変更なし」とし、指摘数を水増ししない。
