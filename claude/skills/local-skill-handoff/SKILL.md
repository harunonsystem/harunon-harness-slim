---
name: local-skill-handoff
description: ローカル executor の Skill metadata を親に返し、選択した正確な参照を task とともに子へ渡す。親からローカル Skill を読めないときの catalog・handoff に使う。通常の Skill 利用や外部 Skill のインストールには使わない。
---

# Local Skill handoff

親がローカル Skill を直接取得できない場合の JSON 接続契約。選択・dispatch は親、実行は子が所有する。この CLI は Skill を自動実行せず、host の内部 API・native catalog 登録・モデル選択・追加セッションを作らない。

CLI は `<skill-dir>/../../policy/skill_catalog.py`。PyYAML は harness の既存 `requirements.txt` に含まれる。依存が無い executor では harness の `.venv` Python を使う。依存・local executor が使えなければ blocker として返し、取得成功を装わない。

1. 親の依頼を受けた local executor は metadata だけを取得する。`--repo` は task の worktree、runtime は実際の子の runtime を指定する。project・runtime・shared を同名でも別の参照として返す。

   ```bash
   python3 <skill-dir>/../../policy/skill_catalog.py --repo <worktree> list --runtime codex --query <仕事の語> --limit 25 --json
   ```

   `truncated` なら query を絞る。`errors` / `errorTotal` は未確認の Skill として扱う。`scripts/skill-map.py` は配布物の棚卸しなので、この user Skill catalog の代用にしない。

2. **親が** entries から exact reference を選び、その entry を `selected.json` に保存する。description・provenance・absolute path を照合し、名前だけで重複を潰さない。`manualOnly` はユーザーがその Skill を明示した場合だけ起動できる。metadata 取得や親の選択は明示起動の代わりにならない。

   ```bash
   python3 <skill-dir>/../../policy/skill_catalog.py --repo <worktree> get --selection-file selected.json --json
   ```

   manual-only の場合のみ、実際のユーザー明示起動に基づく `--explicit-invocation` を付ける。config・適用する references は選択済み本文から特定し、無関係なファイルを一括ロードしない。

3. 親の accepted task を `task.json` に保存する。必須キーは `taskId`, `request`, 元の `arguments`, `acceptance`, `verification`, `authority`, `prohibitions`, `resume`, `reportDestination`, `context`。context は `repository`（canonical host/owner/repo）、absolute `worktree`、accepted immutable `base` SHA、`branch`。resume に既存 state・証跡・現在コマンド・残件を保つ。authority は会話内で承認済みの範囲の記録であり、native consent を発行しない。

   ```bash
   python3 <skill-dir>/../../policy/skill_catalog.py --repo <worktree> prepare --selection-file selected.json --task-file task.json --reference <適用するconfigまたはreference> --json > handoff.json
   ```

4. 親は handoff と独立した accepted task、exact worktree を既存の実行経路で子に渡す。子は実装前に次を実行し、返された selected body と applicable references だけを読む。

   ```bash
   python3 <skill-dir>/../../policy/skill_catalog.py --repo <worktree> load --handoff-file handoff.json --task-file task.json --json
   ```

   task・worktree・HEAD・branch・selected Skill/config/reference が変わったら停止して照合し直す。同じ accepted task の新しい thread は、参照と HEAD が一致すれば再利用できる。モデルは target 設定に従い、handoff や portable Skill 本文で設定しない。

子は元の受入条件・禁止範囲を守り、指定 reportDestination へ結果と証跡を返す。CLI の deterministic 成功は参照付き接続の検証であり、dot host の内部自動 routing や Skill 判断の実測ではない。host の local executor 接続が未提供ならその接続だけを未確認と明示する。
