## Routing（必要時にだけ読む）

通常の小修正では以下を読まない。該当する作業に入るときだけ開く。

| 作業 | 読む |
| --- | --- |
| コード実装・レビューの品質基準（コーディング基準・AI 生成コード検証・過去の失敗事例） | `rules/core-standards.md` |
| コードレビューを実施 | `rules/review-policy.md` |
| Codex レビュー（`/codex:review`）の運用ルール | `rules/codex-review-policy.md` |
| Figma からの実装（Claude のみ。他 runtime には `disabled-skills.json` の common で配布されない） | `figma-implement` skill |
| ブラウザ操作・Web 調査・フロント UI 検証 | `opencli-usage` / `opencli-browser` / `opencli-adapter-author` / `frontend-verify` skill |
| skill / references / scenarios を変更した | `/skill-improvement`（通常の commit / PR は評価後） |
| PR を作成 | `.github/PULL_REQUEST_TEMPLATE.md`（無ければ Summary / Changes / Test plan） |
| 利用可能な skill / command 一覧 | `commands.md` |
| トークン節約（rtk の使い方） | `RTK.md` |

ブラウザ操作のデフォルトは `agent-browser`（headless。ユーザーの画面にウィンドウを出さない）。ユーザーのログイン済みタブが必要な時だけ OpenCLI を bind-first で使い、明示依頼なしに `open`・新規タブ・`INTERCEPT` を実行せず、bind できるタブがなければ中止して確認する。
