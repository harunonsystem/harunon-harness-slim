# pre-review-check / シナリオ B（clean diff: PASSED を返すべき）

## 対象

`~/.claude/skills/pre-review-check/SKILL.md`

## ユーザー入力（diff 想定）

```typescript
// src/features/user/types.ts (新規)
import type { UserRoleType } from '@/types/domains/user';  // 既存型を再利用

export type UserListFilter = {
  role: UserRoleType;
  page: number;
};

// src/features/user/container/UserListContainer.tsx (新規)
import { useRouter } from 'next/router';
import { useFetchUsers } from '../hooks/useFetchUsers';

export function UserListContainer(props: { initialFilter?: UserListFilter }) {
  const router = useRouter();
  if (!router.isReady) return null;
  const { data, isLoading, error } = useFetchUsers(props.initialFilter);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorPage error={error} />;
  if (!data || data.users.length === 0) return <EmptyState />;
  return <UserList users={data.users} />;
}
```

## 要件チェックリスト

1. [critical] 11 カテゴリ全てがチェックされる
2. [critical] PASSED 判定が出る（major/critical finding なし）
3. Finding は「resolved」もしくは最低限の minor のみ
4. 「`/codex:review` に進んで OK」という出力を含む

## subagent 投入プロンプト

```
あなたは ~/.claude/skills/pre-review-check/SKILL.md を白紙で読む実行者です。

## 対象プロンプト
~/.claude/skills/pre-review-check/SKILL.md を Read で読んでください。

## シナリオ（clean diff）
以下の diff はプロジェクト規約を守って書かれています（既存型再利用、props 直接参照、4 状態 UI、no-op onClick なし、ダミーデータ無し）。

（↑ のコードブロックを貼る）

Linear issue 情報は mock（親/兄弟 issue 合意事項は既に準拠しているものとする）。

## 要件チェックリスト
（↑ の 4 項目を貼る）

## タスク
pre-review-check スキルに従って検証し、PASSED/BLOCKED を判定。

## レポート構造
- 成果物: pre-review-check レポート本体
- 要件達成: 各項目 ○/×/部分的
- 不明瞭点: SKILL.md で詰まった箇所
- 裁量補完: 自分の判断で埋めた箇所
- 再試行: 回数

300 語以内で簡潔に。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |
| 2026-04-24 | ○ | 100% | 全達成 | PASSED 判定、全 8 finding resolved、`/codex:review` に進んで OK 出力 |
| 2026-07-11 iter1 | ○ | 100% | 全達成 | 11 カテゴリ版。PASSED、finding 捏造なし |
| 2026-07-11 iter2 | ○ | 100% | 全達成 | 確認不可ラベルを正しく運用し PASS 扱い・BLOCKED 根拠から除外 |
