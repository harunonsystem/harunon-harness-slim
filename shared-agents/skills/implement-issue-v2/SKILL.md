---
name: implement-issue-v2
description: 旧 `/implement-issue-v2` 呼び出しを互換のために受け、implement-issue へ転送する。
---

# implement-issue-v2 compatibility redirect

通常の task intake は [implement-issue](../implement-issue/SKILL.md) を使う。解決済みの task・worktree を含む `$ARGUMENTS` を保持して渡し、同 skill の再利用と実装への引き継ぎに従う。v2 固有の別 workflow はない。
