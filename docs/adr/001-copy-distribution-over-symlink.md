# ADR-001: 全ツールへの配布はファイルコピー方式

## Status: Accepted

## Context

harness から各ツール（Claude Code / Codex / OpenCode）に設定を配布する方式として、symlink とコピーの2案があった。

初期実装（bootstrap.sh）は symlink を使用していたが、以下の理由でコピーに統一した:

- Codex / OpenCode では patches 適用が必要で、symlink では対応できない
- symlink と copy が混在すると配布方式の理解コストが上がる
- どのツールから harness を使い始めても同じ方式で配布される一貫性

## Decision

全ツールへの配布をファイルコピーで統一する。

- **Claude Code**: `bootstrap.sh` で SSOT をそのままコピー（patches なし）
- **Codex / OpenCode**: `/sync-settings --push` で patches 適用済みファイルをコピー

## Consequences

- ドリフト検出が必要（`--check` で定期確認）
- SSOT を変更したら `bootstrap.sh` または `--push` を再実行する運用
- 各ツールの configDir にあるファイルが「今どの版から生成されたか」はトラッキングしない（diff で検出）
- 既存の symlink は `bootstrap.sh` 再実行時に自動的にコピーに置換される

## 追補（2026-06-11）: 第三案「~/.claude を直接 git 管理」は検討済み・保留

本 ADR は symlink vs コピーのみを比較しており、「`~/.claude` 自体を git リポジトリにする」案（dotfiles パターン。runtime 成果物は .gitignore で除外）は未検討だった。この案はライブ編集が即 git diff に現れるため、「ライブ修正が bootstrap で巻き戻る」事故クラス（2026-06-11 の codex review モデル設定インシデント）を検出ではなく構造的に消滅させる。Codex / OpenCode は引き続き apply-patches.py による派生生成ターゲットのまま成立する。

保留の理由: 同日に導入したガード（pre-push の全カテゴリドリフト警告 + bootstrap の上書きサマリー + SSOT-first 原則の明文化）で実害は塞がっており、移行は作業フロー変更を伴う M〜L 級のため釣り合わない。**ドリフト起因の事故が再発した場合は本案への移行を最優先で検討する**（correction-lessons #14「2 回目で構造対策」）。

## 追補（2026-07-26）: 第一根拠の差し替え

Context の第一根拠「Codex / OpenCode では patches 適用が必要で、symlink では対応できない」は失効した。patches 機構は本番 config で一度も使われないまま 2026-07-26 に削除され（ADR-003 追記参照）、AGENTS.md 生成は `expandIncludes` に置き換わっている。上記追補の `apply-patches.py` への言及も同様に歴史的記述。

結論（コピー方式）は以下の現行根拠で維持する:

- distribution ledger（ADR-008）による削除伝播と SHA-256 ドリフト検出はコピー方式が前提
- symlink だとライブ側の編集が SSOT を無言で書き換え、「どのセッションが編集したか」の監査が消える
- omp / portable の `transform`（frontmatter 変換）は派生物の生成であり symlink では表現できない
