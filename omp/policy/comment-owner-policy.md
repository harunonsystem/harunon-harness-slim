# Owned comment gate

`comment-owners.json` が GitHub の操作先ポリシーの SSOT。許可対象は
`github.com/harunonsystem` と `github.com/harunon-labs` だけで、owner は完全一致する。
checkout、remote/pushurl、ログイン actor、親の文章、承認ファイルから owner を推測しない。
許可 owner の repo は public/private のいずれも対象で、visibility を許可条件にしない。
privacy metadata は canonical owner identity や native 同意の代わりにならない。
他 owner、許可 namespace 外の company/project-private、local-only、不明な対象は既存の DENY/ASK を維持する。

## 対応する限定経路

- `gh pr comment <number> --repo github.com/<owner>/<repo> --body '<literal>'`
- `gh pr review <number> --repo github.com/<owner>/<repo> --comment --body '<literal>'`
- `gh api --hostname github.com repos/<owner>/<repo>/pulls/<number>/comments/<comment-id>/replies -X POST -f 'body=<literal>'`
- `gh api --hostname github.com graphql` の下記固定 query と inline field。
  `-f repo=github.com/<owner>/<repo> -f pr=<number> -f thread=<node-id>` を明示する。
  repo/pr は gate が使う scope field で、送信する mutation の変数には含めない。

返信では `-f 'body=<literal>'` を加える。

```graphql
mutation($thread:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$thread,body:$body}){comment{id}}}
```

resolve は実際に finding の修正をレビュー・検証した後だけ呼ぶ。
owner の許可と意味的な修正確認は別の判断である。`rules/review-policy.md` に従う。

```graphql
mutation($thread:ID!){resolveReviewThread(input:{threadId:$thread}){thread{id}}}
```

body-file/stdin、structured/file の query、shell wrapper/chain、動的な shell 展開、
quoted executable/operation、重複・未知の option、別 host、任意の GraphQL operation は自動経路の対象外。
REST reply の thread/comment 検索は各 100 件までで、次ページがあれば推測せず拒否する。
別 connector にはこの例外を拡張しない。

## 実行境界

guard は canonical repo/PR/comment/thread/head を GitHub の読み取りで照合し、
inline 本文を含む capsule を owned helper の `updatedInput` に正規化する。
capsule は実行データであり、owner の許可や native 同意を証明する token ではない。
helper は実際に渡された最終 capsule の owner を再分類し、ID/head/本文 digest を
送信直前の読み取りと照合する。file の再 open や入力の shell 実行はしない。
全ての mutation は固定 `github.com` endpoint 上の確認済み GraphQL node ID に送る。
REST URL の redirect 先を mutation target にしない。

sequential runner は正規化後の command 書き換えを拒否する。Claude の owned parallel
pipeline では RTK がこの subset を書き換えないため、comment guard だけが入力を変更する。
この二つの comment rule の既存 targets は Claude/Pi/OMP/OpenCode。Codex には
例外を拡張せず、既存の permission と他操作の evidence gate を維持する。
他の native input rewriter を導入する場合、この契約を再検証するまでは自動経路を使わない。

hook は `permissionDecision=allow` を返さず、native/platform の独立した拒否や確認を
上書きしない。拒否・失敗後の connector/command shape 変更や mutation の再試行はしない。
この文書・capsule・自己レビュー・kernel の audit-only 証跡はいずれも native consent ではない。
