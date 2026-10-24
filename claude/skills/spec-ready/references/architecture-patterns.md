# アーキテクチャ分類とリリース境界

behavior の互換性と data / contract migration を別軸で判定する。behavior は `compatible` / `parallel-v2`、migration は `none` / `expand-migrate-contract` を基本とする。

## 1. Compatible change

既存 contract / behavior を壊さず追加できる。既存 path を拡張してよい。

## 2. Parallel behavior change

既存 behavior を残したまま新 behavior を安全に並存させる必要がある。
切替可能な境界を作る。

- OpenAPI contract の意味が変わるなら、既存 schema/type に optional field を継ぎ足して曖昧にせず、必要に応じて明示的な v2 contract を作る
- generated type / client / API / UI は、旧 behavior と新 behavior の契約が異なるなら混ぜない
- flag の評価は page / container / service / repository / gateway 等、最も高く安定した seam で原則 1 回だけ行う
- leaf component や domain logic に feature flag 判定を散らさない
- repo が PostHog 等の flag provider を既に使っている場合はそれを使う。新しい provider を勝手に導入しない

```text
Container / Service boundary
  ├─ V1 path
  └─ V2 path
       ↑
  existing feature flag
```

## 3. Data / contract migration

DB や共有データを変える場合、feature flag だけで安全性を作ろうとしない。
原則は **Expand → Migrate → Contract**。

1. 先に backward-compatible な schema / contract を追加
2. old/new consumer が並存できる期間を作る
3. migration / backfill を行う
4. new path の rollout 完了を確認してから old contract を削除

destructive migration、auth / permission / billing 等、repo の既存 policy 上 high-risk な変更は、その policy の gate を保持する。

## 4. Release boundary

コードが main / production に存在することと、ユーザーへ exposure することを分けられるか確認する。
user-visible behavior change で既存の feature flag 基盤がある場合は、release boundary を明示する。

```yaml
release:
  exposure_controlled: true
  boundary: "<page | container | service | repository | gateway>"
  flag: "<existing/new flag key or TBD>"
  rollout: "<repo の既存 rollout policy>"
  cleanup_when: "<100% rollout + 安定確認など>"
```

内部 refactor、test-only、runtime behavior に影響しない docs など、exposure control が不要な変更に flag を強制しない。
