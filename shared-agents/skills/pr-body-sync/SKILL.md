---
name: pr-body-sync
description: 既存 PR の本文を現在の差分と template に合わせて検証・更新する。push 後に本文が古くなったとき、「PR 本文を直して」「PR body 更新」「description 同期」で起動。新規 PR の作成には使わない。
---

# PR body sync

既存 PR の本文を、現在の差分・repo の template・`rules/pr-body.md` に照らして検証し、ずれていれば更新案を作って、ユーザー確認のうえ `gh pr edit` で反映する。
新規 PR の本文は `rules/pr-body.md` に従って書く。この skill は既にある本文の点検と更新だけを担当する。

## 1. 対象を確定する

PR 番号が引数にあればそれを使い、無ければ現在のブランチの PR を解決する。repo identity と対象 PR の公開 base/head SHA・元本文を先に固定する。番号指定した PR の head は現在の checkout HEAD と同じとは限らない。`rules/review-policy.md` の diff baseline に従い、次の手順をそのまま実行する（引数 `$1` は省略可能な PR 番号）。

```bash
set -euo pipefail
unverified() { printf '%s\n' '対象PRは未確認です。取得・identity・SHAを確認してから再開してください' >&2; exit 1; }
TARGET_REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner) || unverified
[[ "$TARGET_REPO" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || unverified
if [ -n "${1:-}" ]; then
  [[ "$1" =~ ^[1-9][0-9]*$ ]] || unverified
fi
metadata=$(gh pr view ${1:+"$1"} --json number,url,baseRefOid,headRefOid,body) || unverified
printf '%s' "$metadata" | jq -e --arg repo "$TARGET_REPO" '
  (.number | type == "number") and .number > 0 and (.number | floor) == .number
  and .url == ("https://github.com/" + $repo + "/pull/" + (.number | tostring))
  and (.baseRefOid | test("^[0-9a-f]{40}([0-9a-f]{24})?$"))
  and (.headRefOid | test("^[0-9a-f]{40}([0-9a-f]{24})?$"))
  and (.body | type == "string")' >/dev/null || unverified
PR_NUMBER=$(printf '%s' "$metadata" | jq -r .number)
[ -z "${1:-}" ] || [ "$PR_NUMBER" = "$1" ] || unverified
BASE_SHA=$(printf '%s' "$metadata" | jq -r .baseRefOid)
HEAD_SHA=$(printf '%s' "$metadata" | jq -r .headRefOid)
TARGET_URL="https://github.com/$TARGET_REPO.git"
git fetch --no-tags --recurse-submodules=no "$TARGET_URL" "$BASE_SHA" || unverified
git fetch --no-tags --recurse-submodules=no "$TARGET_URL" "refs/pull/$PR_NUMBER/head" || unverified
[ "$(git rev-parse 'FETCH_HEAD^{commit}')" = "$HEAD_SHA" ] || unverified
git cat-file -e "$BASE_SHA^{commit}" || unverified
latest=$(gh pr view "$PR_NUMBER" --repo "$TARGET_REPO" --json number,url,baseRefOid,headRefOid,body) || unverified
[ "$(printf '%s' "$latest" | jq -cS .)" = "$(printf '%s' "$metadata" | jq -cS .)" ] || unverified
MERGE_BASE=$(git merge-base "$BASE_SHA" "$HEAD_SHA") || unverified
printf 'repo=%s PR=%s base=%s head=%s merge-base=%s\n' "$TARGET_REPO" "$PR_NUMBER" "$BASE_SHA" "$HEAD_SHA" "$MERGE_BASE"
printf '%s\n' "$metadata"
git diff --stat "$MERGE_BASE" "$HEAD_SHA"
git diff "$MERGE_BASE" "$HEAD_SHA"
```

対象 URL・番号・base/head/merge-base SHA・元本文と、取得した差分を点検記録に残す。fetch 失敗、未知の repo、SHA 不足・不一致・取得中の metadata/本文変更は未確認として停止し、更新案を作らない。権限や sandbox を変更して回避しない。checkout・branch・index・dirty files は変更せず、現在の HEAD や古いローカル ref を代用しない。

## 2. 検証する

repo の `.github/PULL_REQUEST_TEMPLATE.md` があれば読み、本文を欄ごとに次の順で点検する。template が無ければ `rules/pr-body.md` の情報順序（Why / Shape of change / Evidence / Merge risk / Notes）を欄として扱う。

- 必須欄（template の `[必須]`、または Why と Shape of change）が空・placeholder のままになっていないか
- 本文に書かれた変更・ファイル・数値・検証結果が、現在の差分と一致しているか。push で増えた変更が本文に無い、本文にある変更が差分から消えている、のどちらも乖離とする
- 「やらなかったこと」「残件」が、その後の commit で解消済みになっていないか
- `rules/pr-body.md` の書き方（同じ内容の重複、commit log やファイル一覧の転記）に反していないか

結果は欄ごとに「一致 / 乖離（何が）/ 未確認（理由）」で短く並べる。乖離が無ければそう報告して終わる。

## 3. 更新案を作る

- template の見出しと checklist はそのまま残し、乖離のある欄だけ書き換える
- `<!-- xxx:start -->` 〜 `<!-- xxx:end -->` のようなマーカー区間（他の skill や bot が管理する）は中身を変えずに残す
- 事実は差分と実行結果から書く。未実行の検証を実行済みに見せない。分からない事実は `TBD` にする
- 日本語の本文は、構成と事実を確定してから `yomiyasu` を domain `business` で適用する。表現だけを整え、技術的主張・数値・risk・残件は増減させない。`yomiyasu` が利用できない runtime では同じ制約で手動推敲する
- `rules/pr-body.md` の `show-me` 選択基準で図の有効性を判断し、必要な表現だけを使う。推敲・図の判断を実際に行い、hash だけを適用の証拠にしない
- 更新案は現在の本文との差分（変えた欄と変えた理由）として提示する

## 4. 反映する

`gh pr edit` は PR 本文を書き換える外部公開操作なので、更新案を見せてユーザーが承認してから実行する。承認前に実行しない。反映直前に固定した repo の同じ PR metadata・元本文を再取得し、点検記録と比較する。対象 SHA・identity・本文が変わった場合は 1 へ戻り、再点検した更新案への承認を得る。承認された本文をファイルに書き、確定した repo を対象に単独の `gh pr edit <番号> --body-file <path>` で反映する。公開本文を再取得してファイルとの byte equality・マーカー区間・checklist を確認し、PR の URL を報告する。

## 完了条件

- 欄ごとの点検結果を報告している
- 乖離があった場合は、承認を得て反映した本文の URL、または承認待ちの更新案のどちらかを示している
- マーカー区間・checklist・template の見出しが反映後も残っている
