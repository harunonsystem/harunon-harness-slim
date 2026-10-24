# 子Issue分割と公開ルール

親 Issue をそのまま 1 PR にせず、必要な場合は子 Issue に分割する。

## 1. 分割の原則

- 1 Issue = 1 本の振る舞いにする。複数 repo にまたがるなら、同じ Issue のまま repo ごとに PR を出す（`rules/issue-tracker.md`）
- fresh context の agent が単独で理解・実装・検証できる
- main に単独 merge 可能
- tracer-bullet の vertical slice を優先する
- schema / backend / frontend の水平分割だけで終わらせない
- 後続を明確に簡単にする prefactor / additive migration / shared contract は、独立して検証可能なら先行 Issue にしてよい
- stacked PR が必要なら依存を明示し、各段階の main-safety を保つ
- rollout / cleanup が実装と独立するなら別 Issue にする

## 2. 各子 Issue に含める内容

- **What to build**: 完成後に観測できる behavior
- **Acceptance criteria**
- **Blocked by**
- **Verification**
- **Release / flag boundary**（該当する場合）
- **Cleanup obligation**（該当する場合）

## 3. Idempotent な公開手順

READY slice が条件を満たし、未解決の product decision がなければ、通常の粒度確認を挟まず configured issue tracker に子 Issue を作成する。

- 同じ slice の子 Issue が既に存在するなら再利用し、必要な spec / relation だけ更新する。親の外に既存の担当 Issue / PR がある場合は重複作成せず、親へのコメントで参照する
- 新規 slice だけを依存順に作成する
- 契約や依存が未解決の slice は READY とせず、独立した READY slice の公開まで一律に止めない
- 途中で tracker 更新に失敗した場合は、それまでに作成・更新した Issue ID を親 Issue へのコメントに記録して終了する
- 再実行時はその記録と tracker の現状から再開し、作成済み slice を再作成しない

tracker への書き込みは `rules/issue-tracker.md` に従う。作れるのは sub-issue・blocked by リンク・コメントだけで、ラベル・状態・親 Issue の本文は変えない。

親 Issue へのコメントに以下を残す:
- 確定した spec の要点
- slice ごとの architecture classification（behavior / migration）と release boundary
- 作成・再利用した子 Issue と依存関係
- 部分的な publish で止まった場合は、完了済み Issue ID と未作成 slice
