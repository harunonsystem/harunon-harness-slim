---
description: Artifact / HTML レポート / 図版 / チャートの配色・形状トークン。抽象的な設計論ではなく実値のみ。ダーク基調・低彩度。Artifact・archify・dataviz・HTML 生成の着手前に明示 Read する（paths ゲートで非常駐）。
paths:
  - "**/visual-design.md"
  - "**/*.dc.html"
---

## Visual Design Tokens

**この rule は実値の SSOT。`artifact-design` / `dataviz` / `frontend-design` など汎用 skill が配色を語る場合、本 rule の値が優先する。**

汎用 skill は hex を持たず「階層を作れ」「対比を付けろ」という一般論しか与えないため、実際の色はモデルの即興になり、学習分布の中央値（indigo / violet のグラデ、淡い影、丸みの強い角）に落ちる。それを避けるために値を固定する。

### 適用範囲

Artifact（`.html` / `.dc.html`）・archify の図版・HTML レポート・Mermaid のテーマ指定・チャート。会話の応答（markdown）には関係しない。

### パレット

ダークを正とする。ビューアが light テーマの場合も破綻しないよう light を併記するが、light は「同じ色相の明度反転」であって別デザインではない。

```css
:root {
  --bg:      #ffffff;
  --surface: #f6f8fa;
  --border:  #d0d7de;
  --text:    #1f2328;
  --muted:   #656d76;
  --accent:  #0969da;
}
:root:not([data-theme="light"]) { /* @media (prefers-color-scheme: dark) 内に置く */
  --bg:      #0d1117;
  --surface: #161b22;
  --border:  #30363d;
  --text:    #c9d1d9;
  --muted:   #8b949e;
  --accent:  #58a6ff;
}
:root[data-theme="dark"] { /* dark と同じ値を再定義（トグルを両方向で効かせる） */ }
```

意味を持つ色は 3 つだけ。装飾には使わない。

- **success**: `#3fb950` / light `#1a7f37`
- **danger**: `#f85149` / light `#cf222e`
- **warning**: `#d29922` / light `#9a6700`

この 3 色が本パレットの彩度の上限。これより鮮やかな色を新たに導入しない。

### チャート系列色

順番どおりに使う。系列が 6 を超えるなら色を足さず、グルーピングか small multiples に変える。

1. `#58a6ff` blue
2. `#d29922` amber
3. `#56a870` green
4. `#c96f7a` rose
5. `#4fb0ad` teal
6. `#a371f7` purple

purple を 1 番目に置かない（LLM 生成物の既定色として最も手垢が付いている）。

### 形状

- **角丸**: 6px。カード・ボタン・入力すべて同じ。12px 以上は使わない
- **境界**: `1px solid var(--border)`。面の区切りは影ではなく線でやる
- **影**: 使わない。浮かせたい場合は `--surface` との明度差で表現する
- **グラデーション**: 禁止。背景・テキスト・ボーダーすべて単色
- **発光 / ネオン / glassmorphism / backdrop-filter**: 禁止
- **余白**: 4 の倍数（4 / 8 / 12 / 16 / 24 / 32 / 48）。それ以外の値を使わない

### タイポ

- **本文**: `ui-sans-serif, -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif` / 14px / line-height 1.6
- **コード・数値**: `ui-monospace, "SF Mono", Menlo, monospace`。表中の数値は必ず等幅にして桁を揃える
- **見出し**: 本文と同じフォント。サイズは 20 / 16 / 14 の 3 段まで。weight は 600 止まり（700 以上を使わない）
- 文字色は `--text` と `--muted` の 2 つだけ。第 3 の中間色を作らない

### Mermaid

テーマは指定する（既定のパステルを出さない）。

```
%%{init: {'theme':'base','themeVariables':{
  'background':'#0d1117','primaryColor':'#161b22','primaryTextColor':'#c9d1d9',
  'primaryBorderColor':'#30363d','lineColor':'#8b949e','fontSize':'14px'}}}%%
```

### 検証

生成後に自分の出力を読み返して次を確認する。1 つでも該当したら直してから提出する。

- `linear-gradient` / `radial-gradient` / `box-shadow` / `text-shadow` / `backdrop-filter` が含まれていないか
- ここに列挙していない hex が含まれていないか（`rgba(0,0,0,.x)` の影も含む）
- `border-radius` が 6px 以外になっていないか
