# ADR-012: Harness を worker orchestration の coordinator にする

## Status: Accepted

## Context

Core Workflow（`policy/harnessctl.py` + `workflows/change.json`）は worktree 単位の task state・revision compare-and-swap・repo/worktree binding・review evidence・publish 認可を既に持つ。一方で「誰がどの phase を実装しているか」「reviewer に何を渡したか」「worker が何を根拠に完了と言ったか」は state に無く、coordinator セッションの会話メモリにしか存在しない。

複数の executor（Claude Code / Codex / pi）を worker として使い分ける運用が増え、worker 間の通信 transport として agmsg（`fujibee/agmsg`、bash + sqlite3 の skill。team + agent name でアドレッシング、message は append-only の monotonic id 付き、thread / ack / blocking wait は無し）が手元にある。ここで別 coordinator（Orca 等）や別メモリ層を足すと、workflow state と assignment の真実が 2 系統に割れ、どちらが正しいか分からなくなる。

Orca は run / task / worker_done / decision gate という概念の参考にはするが導入しない。Core Workflow は既に直線 FSM と認可 gate を持ち、足りないのは worker orchestration と provenance の接続点だけだからである。

構成の言い換え: Harness が脳（state / lifecycle / 認可 / provenance）、agmsg が神経（transport）、Otty が手足と画面（表示・端末操作）、Claude / Codex / pi が作業者（executor）。

## Decision

Core Workflow の task state に **assignment** を一級の状態として追加し、worker orchestration を kernel の外に作らない。

### 1. state schema（schemaVersion 2）

`state.assignments: []` を追加する。配列の最後の要素が現在の assignment。履歴を残すのが provenance の目的なので単一オブジェクトにしない。

```json
{
  "role": "implement",
  "executor": "codex",
  "workerId": "<executor が返す session id 等>",
  "status": "assigned",
  "correlationId": "<kernel が生成>",
  "subjectSha": "<割当時 HEAD>",
  "dispatch": null,
  "resultSha": null,
  "abandonReason": null
}
```

- `role`: `implement` | `review`
- `status`: `assigned` → `dispatched` → `reported`、または任意の時点で `abandoned`
- `dispatch`: `{ "transport": "agmsg", "ref": { "team": ..., "to": ... }, "at": <ISO 8601> }`。transport の内部 id は持たない
- `subjectSha`: implement role では割当時の base、review role ではレビュー対象 HEAD
- `correlationId`: Harness が発行し、dispatch する message 本文の先頭に埋める。agmsg に thread が無いため、worker の返信をどの assignment への報告か紐づける鍵を transport 非依存に持つ

既存の `local-review` evidence には `assignmentIndex` を追加する（kind は変えない。`pr.create` の authorize が kind を見ているため）。新設する evidence は `{ "kind": "worker-report", "trust": "audit-only", "assignmentIndex", "executor", "workerId", "subjectSha", "resultSha", "artifact", "checks": [{ "command", "exitCode" }] }`。変更ファイル一覧は worker の自己申告を信じず coordinator が `git diff --stat` で再計算するため持たない。

### 2. kernel イベント

`apply` に 4 type を追加する。

| type | 前提 | 効果 |
| --- | --- | --- |
| `assignment.create` | phase が `implement` または `review`、現在の assignment が無いか `reported` / `abandoned` | 要素を追加（`assigned`）、`correlationId` を生成して返す |
| `assignment.dispatched` | `assigned` | `dispatched`、`dispatch` を記録 |
| `assignment.report` | `dispatched` | `reported`、evidence を追加。implement role は `resultSha == HEAD` かつ `subjectSha` が `resultSha` の祖先（`git merge-base --is-ancestor`）を要求。review role は既存 `review.attach` と同じ検証（`subjectSha == HEAD`、artifact 実在、`reviewAttempts` 上限） |
| `assignment.abandon` | `assigned` または `dispatched` | `abandoned`、理由必須。timeout は kernel に持たず coordinator の運用値 |

既存の `review.attach` は `assignment.report(role=review)` の別名として維持する（OpenCode の `harness_workflow` 等の既存呼び出しを壊さない）。

`phase.advance implemented` に gate を足す: assignment が存在するなら最後の要素が `reported` であること。assignment が無い直接実装は従来どおり通す（rigor profile が casual なタスク、委譲コストが上回る軽微修正は worker を立てない）。塞ぐのは「dispatched のまま先へ進む」経路だけ。

phase 列は変えない。変えると `workflow.version` が変わり全 active state が `WORKFLOW_VERSION_MISMATCH` になる。

### 3. 境界

- **kernel は transport を叩かない。** dispatch された事実の記録までが kernel、送信は coordinator 側 adapter の責務。kernel の副作用は今日どおり git の読み取りだけ
- **完了報告は coordinator が検収して state に入れる。** worker は agmsg で報告本文を送るだけで `assignment.report` を直接叩かない。state.json は worktree 単位で `validate_context` に守られており、別 worktree の worker は `STATE_CONTEXT_MISMATCH` になる。加えて自己申告を検収してから記録する方が provenance として正しい
- **同時 1 assignment。** DAG は表現しない。並列が要るなら task を分けて worktree ごとに state を持つ（既存の per-worktree 設計がそのまま隔離になる）
- **fix loop（`decide → fix_selected → implement`）では新しい `assignment.create` が必須。** 同じ worker に戻すかは coordinator の判断で kernel は関知しない
- **Otty は harness の依存にしない。** 表示・端末操作レイヤーとして位置づけるが、Otty 向け成果物は配布せず、run-change は Otty 無しで成立する。連携は otty-plus の実体確認後に別 ADR

### 4. registry

- `policy/executors.json`: executor 名 → 担える role。初期値 `claude: [implement, review]`、`codex: [implement, review]`、`pi: [implement]`（pi は sandbox 下で無音失敗する実績があり reviewer には使わない）。omp / opencode は worker としての spawn 経路が確認できてから追加。kernel は `UNKNOWN_EXECUTOR` / `EXECUTOR_ROLE_UNSUPPORTED` で弾く。起動方法は registry に書かない（adapter の責務）
- `policy/transports.json`: `agmsg: { root: "~/.agents/skills/agmsg", send: "scripts/send.sh", inbox: "scripts/inbox.sh", ... }`。`harness-doctor.sh` が存在確認する（agmsg は unmanaged allowlist の外部アプリで、harness 参照済みなのに未インストールだった実例がある）

### 5. adapter と運用

- `run-change/scripts/harness.py` に `assign` / `dispatched` / `report` / `abandon` を追加。`assign` は `correlationId` を stdout で返す。OpenCode `harness_workflow` にも同じ 4 操作を追加し `capability-contract.json` で parity を担保
- agmsg の team は repo 単位、agent 名は role 固定（`coordinator` / `implementer` / `reviewer`）。同時 1 assignment なので衝突しない。`workerId` は agmsg の名前とは別に session を識別する値
- worker の起動は当面 `/agmsg spawn <type> <name> --boot-prompt`（ready 待ちを持つ）。Otty 経由への差し替えは adapter 層だけの変更
- coordinator の受信は agmsg `turn` モード（Stop hook）を最低要件とし、Claude Code では `monitor` を任意で足す。run-change は Codex / pi / omp でも coordinator になれる建前のため、Claude 専用機能を必須にしない

### 6. 互換

schemaVersion 1 の state は `task_is_active` が false（complete、または intake で revision 0）なら version を bind せず読め、`task.start` で上書きできる。active な v1 state は止め、そのタスクは旧 kernel で完了させる。永続ブロックを作らない既存原則を守る。

## Consequences

- assignment の真実は state.json だけになる。会話メモリや外部 coordinator に同じ情報を持たない
- worker の完了報告は evidence として state に残り、`assignments[]` と合わせて「誰が・どの HEAD に対して・何を根拠に」完了と言ったかが provenance として追える
- agmsg 実送受信は harness のテストに含めない（CI に無い）。担保は kernel / adapter / validator のテストと doctor の存在確認
- 実装は 3 PR に分ける: (1) kernel + schema + adapter + テスト、(2) registry + validator + doctor + 配布契約、(3) SKILL.md の coordinator 手順 + OpenCode parity
- 導入しなかった案: Orca の丸ごと導入（coordinator と state が二重化）、kernel が agmsg を直接叩く（副作用ゼロの設計とテスト移植性が崩れる）、timeout の kernel 内判定（時刻を判断材料にしない設計に反する）、phase 追加による表現（全 active state が version mismatch になる）
