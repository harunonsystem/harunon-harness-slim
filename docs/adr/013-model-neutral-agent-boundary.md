# ADR-013: Model/provider に依存しない agent 境界と target socket

## Status: Accepted

## Context

モデル、provider、認証契約、推論能力は交換される。にもかかわらず現在の model id や品質・速度の順位を Skills・rules・Agents.md に埋め込むと、モデル交換のたびに durable な指示まで書き換わり、別 runtime への配布で前提が漏れる。

`packages/core/model-routing.json` は ADR-010 の役割別ルーティングを 1 つの current policy ledger に集約したが、portable な指示との境界と、投影先が target config に所有されていることは明文化されていなかった。

## Decision

### Durable contract

- Skills・rules・共有または target の `AGENTS.md` に置くのは、観測可能な不変条件・境界・停止条件だけにする。
- 現行の model/provider/version、品質・速度・コストの順位、特定モデル向けの prompt tuning は durable 層に置かない。
- model/provider-specific skill は例外として target 固有の末端に置き、`packages/core/disabled-skills.json` で配布 target を限定する。`efficient-fable` のような Claude 専用 skill や Codex 専用の `codex-reset-credits` を共有 runtime に配布しない。
- `packages/core/CLAUDE.md` と target の設定・拡張は runtime edge であり、そこで必要な model-specific tuning を保持できる。ただし共有文書へ逆流させない。

### Adapter socket

`packages/core/model-routing.json` を model/provider 選択の唯一の current policy ledger として維持する。別の model table や runtime ごとの policy SSOT は作らない。

交換可能な契約は次の形に固定する。

```text
runtime / role / purpose → model alias / effort → target projection
```

`packages/core/model-routing.json` の具体値は `scripts/sync-model-routing.py` が target の宣言へ投影する。`packages/targets/*/config.json` の `settingsSync.source` と `distribute[*].source` が projection の所有 socket であり、projection を手編集して別経路を作らない。

`scripts/harness_lib/validators/model_portability.py` は次を検証する。

- portable な rules / shared fragments / target `AGENTS.md` / `RTK.md` / `commands.md` に ledger の model id が混入していないこと
- routing table の全 projection path が該当 runtime の target config socket に所有されていること
- malformed な target config を traceback ではなく finding として報告すること

### Failure and change procedure

profile が存在しない、選べない、または provider が利用できない場合は暗黙の model/provider fallback をせず、明示的なエラーまたは報告にする。

モデル交換だけなら current policy ledger と target projection を更新し、共有 Skills・rules・Agents.md は変更しない。不変条件・境界が変わるときだけ durable contract と validator、必要ならこの ADR を更新する。

## Consequences

- モデル交換の変更面が ledger・sync・target projection に閉じ、portable な指示の再調整を不要にできる。
- portable 層へ model id が逆流した場合と、投影先の所有宣言が欠けた場合を `validate-harness.py` で検出できる。
- provider 契約終了時は自動で別契約へ流れず、利用可能な候補・品質・コストを確認した明示的な切替が必要になる。
- 具体的な model/provider の現行値は ADR-010 と current policy ledger に残るが、portable 文書に複製しない。

## Rejected alternatives

- model ごとの nested profile や第二の policy table: SSOT が増え、同期・drift の責任が分散するため採用しない。
- 全 `packages/core` 文書の一律スキャン: Claude 専用 `CLAUDE.md` や target edge の tuning まで拒否し、末端への隔離を検証できないため採用しない。
- provider 不調時の暗黙 fallback: 品質・料金・認証境界を隠し、障害時の再現性を壊すため採用しない。
