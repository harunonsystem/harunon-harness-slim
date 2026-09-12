# cr / シナリオ A（typical: TS プロジェクトの問題入り diff）

## 対象

`~/.claude/skills/cr/SKILL.md`

## ユーザー入力（diff 想定）

```typescript
// src/features/user/types.ts (新規)
export type UserRoleType = 'admin' | 'general';  // 既存は '@/types/domains/user' に 'admin' | 'member' が定義済み

// src/features/user/hooks/useFetchUsers.ts (新規)
const MOCK_USERS = [
  { id: 1, name: '川上 麻衣子', age: 42 },
  { id: 2, name: '山田 太郎', age: 35 },
];
export function useFetchUsers() {
  return { data: { users: MOCK_USERS }, isLoading: false, error: null };
}

// src/features/user/container/UserListContainer.tsx (新規)
export function UserListContainer(props: { title?: string }) {
  const { basicInfo } = props;
  const { data } = useFetchUsers();
  return (
    <div>
      <button onClick={() => undefined}>保存</button>
      <button onClick={() => undefined}>もっと見る</button>
      {data.users.map(u => <div>{u.name}</div>)}
    </div>
  );
}
```

## 要件チェックリスト

1. [critical] Step 0 で Rails でないと判定し、以降の Step に進む
2. [critical] Output Contract（Result / Blocking / Non-blocking / AI Antipattern Check / Summary）の形式に従う
3. [critical] 全 blocking 指摘に finding_id が付与される（RVW-/ARCH-/SEC- prefix 維持）
4. 品質・構造・セキュリティの 3 観点それぞれの分析が finding に反映される
5. major 以上の指摘が 3 件以上（ダミーデータ、no-op onClick、既存型不整合が候補）
6. finding が severity 順にソートされる

## subagent 投入プロンプト

```
あなたは ~/.claude/skills/cr/SKILL.md を白紙で読む実行者です。

## 対象プロンプト
~/.claude/skills/cr/SKILL.md を Read で読んでください。参照されている ~/.claude/rules/review-policy.md も必要に応じて読んでよい。

## シナリオ
プロジェクトルートに Gemfile は存在しない（TS/Next.js プロジェクト）。ユーザーが /cr（引数なし）を実行した。ローカル変更は上記 diff とする（実ファイルは存在しないので git コマンドは実行せず、この diff を対象として扱う）。

環境 mock: reviewer / architecture-reviewer / security-reviewer の subagent spawn が不可能な場合は、3 観点を自分で独立に順番に分析して代替してよい（裁量補完に明記）。

## 要件チェックリスト
（↑ の 6 項目を貼る）

## タスク
1. 対象プロンプトに従ってレビューを実行し、Code Review Report を生成する。
2. レポート構造（成果物 / 要件達成 ○×部分的 / 不明瞭点 / 裁量補完 / 再試行）で返答する。

全体 700 語以内。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |
| 2026-07-11 iter1 | ○ | 100% | 全達成 | REJECT、blocking 5 件。3 観点の実 spawn 成功。不明瞭点: Output Contract 例の F-001 表記と Step 3 の prefix 維持が矛盾 → 例を RVW-/ARCH- 表記に統一し ID ルールを明文化 |
