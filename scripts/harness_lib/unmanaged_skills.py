"""未管理スキルの検出。

skill の投入経路は harness 配布（core / extras）と rulesync（外部 upstream、ADR-011）の
2 つだけ。`npx skills add` や手コピーはターミナルから直接行われ agent 側 hook では
捕まえられないため、ライブ側ディレクトリと SSOT を突き合わせて検出する。

対象は ~/.claude/skills（Claude Code）と ~/.agents/skills（codex / opencode / pi / omp の
共有ロードパス）。管理外だが許可するもの（installer で入るアプリ等）は
packages/core/unmanaged-skills-allowlist.json に理由付きで宣言する。

以前は .githooks/pre-push に bash で埋め込まれ push を block していたが、push する PR と
無関係なローカル環境の状態で push を止めていたため、環境診断（harness-doctor.sh）の
責務に移した（2026-08-29）。pre-push は同じ判定を警告表示にだけ使う。

CLI:
    python3 -m harness_lib.unmanaged_skills --repo-root <repo> --claude-dir <dir> \
        --agents-skills-dir <dir> [--allowlist <json>] [--lock <rulesync.lock>]

stdout: 1 行目は `extras=known` / `extras=unknown`（extras submodule の skills/ が
読めたか）。以降は未管理 skill のパスを 1 行 1 件。
exit 1: 未管理があり、かつ extras を判定できた。それ以外は exit 0。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOWLIST_REL = Path("packages/core/unmanaged-skills-allowlist.json")
LOCK_REL = Path("rulesync.lock")
CORE_SKILLS_REL = Path("packages/core/skills")
EXTRAS_SKILLS_REL = Path("packages/extras/_active/skills")


@dataclass(frozen=True)
class UnmanagedReport:
    extras_known: bool
    unmanaged: tuple[Path, ...]

    @property
    def blocking(self) -> bool:
        """未管理があり、かつ extras 由来でないと言い切れる場合だけ block 相当。"""
        return self.extras_known and bool(self.unmanaged)


def _dir_names(path: Path) -> set[str]:
    # ドットエントリ（.DS_Store / .claude 等）は skill ではない。旧 bash 実装は `ls` が
    # 隠しファイルを出さないことで暗黙に除外していたので、同じ契約を明示する。
    if not path.is_dir():
        return set()
    return {p.name for p in path.iterdir() if not p.name.startswith(".")}


def _read_json_or_empty(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _allowlisted(allowlist: Path) -> set[str]:
    data = _read_json_or_empty(allowlist)
    return {k for k in data if not k.startswith("$")}


def allowlisted_skill_names(repo_root: Path) -> frozenset[str]:
    """unmanaged-skills-allowlist.json で明示許可された skill 名。

    未管理 skill guard と distribute の --prune が同じ宣言を見るための唯一の入口。
    パス（ALLOWLIST_REL）と `$` キーの除外規則をここ以外に複製しない。
    """
    return frozenset(_allowlisted(repo_root / ALLOWLIST_REL))


def _curated(lock: Path) -> set[str]:
    data = _read_json_or_empty(lock)
    return {n for s in data.get("sources", {}).values() for n in s.get("skills", {})}


def managed_skill_names(repo_root: Path, allowlist: Path, lock: Path) -> tuple[set[str], bool]:
    """管理下の skill 名集合と、extras submodule を判定できたかを返す。"""
    extras_dir = repo_root / EXTRAS_SKILLS_REL
    extras_known = extras_dir.is_dir()
    managed = (
        _dir_names(repo_root / CORE_SKILLS_REL)
        | _dir_names(extras_dir)
        | _curated(lock)
        | _allowlisted(allowlist)
    )
    return managed, extras_known


def find_unmanaged(
    repo_root: Path,
    live_dirs: list[Path],
    allowlist: Path | None = None,
    lock: Path | None = None,
) -> UnmanagedReport:
    managed, extras_known = managed_skill_names(
        repo_root,
        allowlist or repo_root / ALLOWLIST_REL,
        lock or repo_root / LOCK_REL,
    )
    unmanaged: list[Path] = []
    for live in live_dirs:
        for name in sorted(_dir_names(live)):
            if name not in managed:
                unmanaged.append(live / name)
    return UnmanagedReport(extras_known=extras_known, unmanaged=tuple(unmanaged))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo-root", required=True, type=Path)
    p.add_argument("--claude-dir", required=True, type=Path, help="~/.claude 相当（skills/ を見る）")
    p.add_argument("--agents-skills-dir", required=True, type=Path, help="~/.agents/skills 相当")
    p.add_argument("--allowlist", type=Path, default=None)
    p.add_argument("--lock", type=Path, default=None)
    ns = p.parse_args(argv)

    report = find_unmanaged(
        ns.repo_root.resolve(),
        [ns.claude_dir / "skills", ns.agents_skills_dir],
        allowlist=ns.allowlist,
        lock=ns.lock,
    )
    print("extras=known" if report.extras_known else "extras=unknown")
    for path in report.unmanaged:
        print(path)
    return 1 if report.blocking else 0


if __name__ == "__main__":
    sys.exit(main())
