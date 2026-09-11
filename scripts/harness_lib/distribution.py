"""深いモジュール: Distribution 統合配布パイプライン (#006 C1/C2).

Design goals (Codebase Design):
- Interface を小さく: Distribution(repo, fs) の 2 引数で全操作を完結
- Leverage を高く: manifest/inspect/push/pull/ledger/backup を 1 クラスに集約
- 情報隠蔽: resolver / settings_sync / merge の詳細を外に漏らさない
- Seam: FileSystem をコンストラクタ注入 (Local-substitutable)

外部 import 境界はこのモジュール 1 枚。実装詳細は distribution_state へ隠蔽する。
"""

from __future__ import annotations

from pathlib import Path

from .distribution_state import (
    ApplyResult,
    DistributionInspection,
    DistributionPlan,
    FileSystem,
    PathFileSystem,
    apply,
    inspect as _inspect,
    plan_pull as _plan_pull,
    plan_push as _plan_push,
)
from .resolver import Manifest, manifest as _manifest


class Distribution:
    """深いモジュール: 配布パイプライン全体を 1 インタフェースで提供.

    Args:
        repo: リポジトリルート (SSOT 側).
        fs: 配布先のファイルシステム seam. 省略時は PathFileSystem (本番).
            テストは record/in-memory adapter を注入してステートを固定できる.

    使用例:
        dist = Distribution(repo)
        inspection = dist.inspect("codex")
        if inspection.has_drift:
            plan = dist.plan_push("codex", dry_run=True)
            ...
        plan, result = dist.push("codex", dest_dir=Path("/tmp/live"))
    """

    def __init__(self, repo: Path | str, fs: FileSystem | None = None) -> None:
        self.repo: Path = Path(repo)
        self.fs: FileSystem = PathFileSystem() if fs is None else fs

    # -- manifest / list -----------------------------------------------------

    def manifest(self, target: str) -> Manifest:
        """対象ターゲットの解決済み manifest を返す (resolver 委譲)."""
        return _manifest(target, self.repo)

    def list_paths(self, target: str) -> list[str]:
        """manifest の相対パス一覧をソート済みで返す (CLI --list 用)."""
        return sorted(self.manifest(target).files.keys())

    # -- inspect / check -----------------------------------------------------

    def inspect(self, target: str, live_dir: Path | str | None = None) -> DistributionInspection:
        """配布先の状態を不変スナップショットとして観測する (read-only)."""
        dest = Path(live_dir) if live_dir is not None else None
        return _inspect(target, self.repo, dest, fs=self.fs)

    # -- push ----------------------------------------------------------------

    def plan_push(
        self,
        target: str,
        dest_dir: Path | str | None = None,
        *,
        dry_run: bool = False,
        prune: bool = False,
    ) -> DistributionPlan:
        """push の不変プランを構築する (I/O は観測のみ, 書き込みなし)."""
        dest = Path(dest_dir) if dest_dir is not None else None
        return _plan_push(target, self.repo, dest, dry_run, prune, fs=self.fs)

    def push(
        self,
        target: str,
        dest_dir: Path | str | None = None,
        *,
        dry_run: bool = False,
        prune: bool = False,
    ) -> tuple[DistributionPlan, ApplyResult]:
        """plan_push -> apply を一括実行する高レバレッジ操作."""
        plan = self.plan_push(target, dest_dir, dry_run=dry_run, prune=prune)
        return plan, apply(plan, fs=self.fs)

    # -- pull ----------------------------------------------------------------

    def plan_pull(
        self,
        target: str,
        live_dir: Path | str | None = None,
        *,
        dry_run: bool = False,
    ) -> DistributionPlan:
        """pull の不変プランを構築する."""
        live = Path(live_dir) if live_dir is not None else None
        return _plan_pull(target, self.repo, live, dry_run, fs=self.fs)

    def pull(
        self,
        target: str,
        live_dir: Path | str | None = None,
        *,
        dry_run: bool = False,
    ) -> tuple[DistributionPlan, ApplyResult]:
        """plan_pull -> apply を一括実行."""
        plan = self.plan_pull(target, live_dir, dry_run=dry_run)
        return plan, apply(plan, fs=self.fs)


__all__ = [
    "Distribution",
]
