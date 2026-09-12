# reviewer / シナリオ A（典型：Boy Scout Rule と severity 判定）

## 対象

`~/.claude/agents/reviewer.md`

## ユーザー入力（diff 想定）

```typescript
// 変更ファイル: src/utils/userName.ts (既存修正)
export function formatUserName(user: { firstName: string; lastName: string }) {
  // ↓ 新規追加行
  const fallbackName = user.firstName ?? 'unknown';  // 必須データへのフォールバック（major）
  // ↓ 既存コード（変更なしだが変更ファイル内）
  if (!user) return '';  // エラー握りつぶし既存（Boy Scout Rule 対象）
  return `${user.lastName} ${fallbackName}`;
}

// 変更ファイル: src/utils/userName.test.ts (新規)
// テストが追加されていない（major: テストなしの新しい振る舞い）
```

## 要件チェックリスト

1. [critical] Finding ID は `RVW-<番号>` 形式
2. [critical] `critical`/`major` finding が 1 件でもあれば REJECT 判定
3. [critical] `user?.firstName ?? 'unknown'` に対して major finding が挙がる（フォールバック禁止）
4. Boy Scout Rule を適用し、変更ファイル内の既存 `if (!user) return ''` も REJECT 対象として挙がる
5. 「テストなしの新規振る舞い」が major finding に挙がる
6. Severity は review-policy.md 準拠（critical/major/minor の 3 段階）
7. 条件付き APPROVE（minor のみ許容）を遵守

## subagent 投入プロンプト

```
あなたは ~/.claude/agents/reviewer.md の reviewer エージェントを白紙で読んで実行する立場です。

## 対象プロンプト
~/.claude/agents/reviewer.md を Read で読んでください。参照ルール（review-policy.md, core-standards.md）は必要に応じて読む。

## シナリオ（typical diff）
以下の diff をレビューしてください。

（↑ のコードブロックを貼る）

## 要件チェックリスト
（↑ の 7 項目を貼る）

## タスク
reviewer エージェントとしてレビューを実行し、Output Contract 通りのレポートを返す。

## レポート構造
- 成果物: Code Review Report 本体
- 要件達成: 各項目 ○/×/部分的
- 不明瞭点: reviewer.md で詰まった箇所
- 裁量補完: 自分の判断で埋めた箇所
- 再試行: 回数

500 語以内で簡潔に。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |
| 2026-04-24 | ○ | 100% | 全達成 | REJECT 判定、3 major finding（フォールバック、Boy Scout、テストなし）、RVW- 形式使用 |
