# pre-review-check / シナリオ A（典型：11 カテゴリ全部触る diff）

## 対象

`~/.claude/skills/pre-review-check/SKILL.md`

## ユーザー入力（diff 想定）

```typescript
// src/features/user/types.ts (新規)
export type UserRoleType = 'admin' | 'general';  // 既存ドメイン型と不整合の可能性

// src/features/user/hooks/useFetchUsers.ts (新規)
const MOCK_USERS = [  // hook 内にダミーデータ直書き（PII 風）
  { id: 1, name: '川上 麻衣子', age: 42 },
  { id: 2, name: '山田 太郎', age: 35 },
];
export function useFetchUsers() {
  return { data: { users: MOCK_USERS }, isLoading: false, error: null };
}

// src/features/user/container/UserListContainer.tsx (新規)
export function UserListContainer(props: { title?: string }) {
  const { basicInfo } = props;  // 分割代入（プロジェクト規約は直接参照）
  const { data } = useFetchUsers();
  return (
    <div>
      <button onClick={() => undefined}>保存</button>  {/* no-op onClick */}
      <button onClick={() => undefined}>もっと見る</button>  {/* no-op onClick */}
      <Label type="fillSoft" variant="primary">admin</Label>  {/* variant未対応の可能性 */}
      {data.users.map(u => <div>{u.name}</div>)}
    </div>
  );
}

// src/pages/users/index.tsx (変更)
+ import { UserListContainer } from '@/features/user/container/UserListContainer';
```

## 要件チェックリスト

1. [critical] 全 11 カテゴリが検証され、Finding もしくは OK として記録される
2. [critical] Finding ID は `PRC-<番号>` 形式
3. [critical] 最低 3 件の major finding が検出される（ダミーデータ直書き、分割代入、no-op onClick が最低限）
4. BLOCKED / PASSED 判定が出る
5. Output Contract のフォーマット（Summary + Findings + Next Action）に従う
6. `/codex:review` 前に対処すべきものが明示される

## subagent 投入プロンプト

```
あなたは ~/.claude/skills/pre-review-check/SKILL.md を白紙で読む実行者です。

## 対象プロンプト
~/.claude/skills/pre-review-check/SKILL.md を Read で読んでください。

## シナリオ（typical diff、複数問題を含む）
以下の diff がステージング予定として存在すると仮定。

（↑ のコードブロックを貼る）

なお Linear issue 情報はこのシナリオでは参照不可（mock: 親 issue なし、兄弟 issue なし）として扱ってよい。

## 要件チェックリスト
（↑ の 6 項目を貼る）

## タスク
pre-review-check スキルに従って上記 diff を検証し、Output Contract 通りのレポートを出力する。

## レポート構造
- 成果物: pre-review-check レポート本体
- 要件達成: 各項目 ○/×/部分的
- 不明瞭点: SKILL.md で詰まった箇所
- 裁量補完: 自分の判断で埋めた箇所
- 再試行: 回数

500 語以内で簡潔に。
```

## 最終実行結果

| 日付 | 判定 | 精度 | [critical] | 備考 |
| --- | --- | --- | --- | --- |
| 2026-04-24 | ○ | 100% | 全達成 | BLOCKED 判定、8 finding（new: 6, resolved: 2）、major 3+ 件検出 |
| 2026-07-11 iter1 | ○ | 100% | 全達成 | 11 カテゴリ版。BLOCKED、7 finding。不明瞭点: 確認不可の記録方法・PII severity 基準 → skill に判定基準 3 行を追記 |
| 2026-07-11 iter2 | ○ | 100% | 全達成 | 追記した判定基準（確認不可 / PII critical）を実行者がそのまま採用。残差は Output Contract の表示書式のみ → 4 値定義を追記して収束 |
