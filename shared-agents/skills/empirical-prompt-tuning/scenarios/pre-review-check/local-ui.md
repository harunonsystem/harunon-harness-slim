# pre-review-check / untracked UI

## 対象

`packages/core/skills/pre-review-check/SKILL.md`

## ユーザー入力

この資料はレビュー対象の全入力です。現在のHarness checkoutは対象外。実コードや外部サービスの変更は禁止。
ユーザー依頼: 以下のローカル変更を pre-review-check でチェックして報告してください。修正はまだしないでください。

git status --short は ?? src/UserList.tsx。HEAD と main の差分は空。未追跡ファイルも今回の実装です。
Issue/Figma指定なし。プロジェクト規約は通常のReact関数コンポーネント、propsの分割代入可。MSW/Storybook/CSS Modulesの導入はありません。
既存型: src/domain.ts:1 export type UserRole = 'admin' | 'member';
useUsers はreact state hookを使う既存hook。常に呼び、enabledでfetchを制御できます。getRouterのisReadyは初回false、次のrenderでtrueになります。
src/UserList.tsx 全文:
```tsx
import { useUsers } from './useUsers';
import { getRouter } from './router';
export function UserList({ title }: { title: string }) {
  const router = getRouter();
  if (!router.isReady) return null;
  const { data, isLoading, error } = useUsers();
  if (isLoading) return <div>Loading</div>;
  if (error) return <div role="alert">Failed</div>;
  if (data.users.length === 0) return <div>Empty</div>;
  return <div>{title}<button onClick={() => undefined}>保存</button></div>;
}
```
lint/testは未実行。コードの証拠に基づく判定を返し、実行済みとしないでください。補助skill/CLIはこのfixtureでは利用不可。
成果物はレポート。その後に不明瞭点、裁量補完、再試行回数を簡潔に添える。

## 要件チェックリスト

1. [critical] untracked `src/UserList.tsx` を今回の対象として読む
2. [critical] early return後のHookとno-op操作を証拠付きで検出する
3. [critical] props分割代入、MSW/Storybook未導入を違反にしない

## subagent 投入プロンプト

上のユーザー入力だけを読み、`pre-review-check` に従って修正なしのレポートを返す。実checkout、変更、外部アクセスは行わない。

## 最終実行結果

2026-09-11 fresh評価: critical要件を達成。Hook順序とno-opを検出し、未導入ツールとprops規約を問題にしなかった。
