"""harness_lib.resolver — 配布期待値の解決（Manifest）。

config.json の distribute 宣言を解釈し、
「相対パス → 期待内容（bytes）」のマップ（Manifest）を生成する。
live との比較（drift 検出）は distribution_state.inspect が担う。
"""
from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_target
from .curated_skills import invalid_skill_names, list_curated_skills
from .frontmatter import transform_skill_md
from .includes import expand_includes
from .paths import safe_relative


_SKILLS_DEST = "skills/"
# rulesync が upstream から取得する外部 skill の実体（gitignore 済・rulesync install が生成）。
# distribute[dest].source にこの値を追加すると、外部 skill も通常の manifest エントリとして
# ledger 管理される（ADR-011 Update 2026-08-30）。未取得（rulesync install 未実行）は
# uninitialized submodule と同様に skip（incomplete）扱いし、取得済みなのに rulesync.lock
# 宣言分が揃っていない場合だけ fail-closed で止める。
CURATED_SKILLS_SOURCE = ".rulesync/skills/.curated"

# hook が隣の lib を参照する唯一の書き方（`source "$HOOK_DIR/lib/<name>.sh"` /
# `[ -r "$HOOK_DIR/lib/<name>.sh" ]` / `LIB="${HOOK_DIR}/lib/<name>.sh"`）。
# distributeEntry の `hookLibClosure: true` はこの参照を辿って lib の推移閉包を配布物に含める。
# `|| true` のソフト参照や `[ -r ]` ガード付きの任意参照も含める: 欠けていれば hook は
# 「その機能なし」で動くが、SSOT が配る意図の機能は揃っている状態を配布物とみなす。
HOOK_LIB_REF = re.compile(r"\$\{?HOOK_DIR\}?/lib/([A-Za-z0-9._-]+\.sh)")


def hook_lib_closure(hooks: dict[str, bytes], libs: dict[str, bytes]) -> set[str]:
    """hook 群が `$HOOK_DIR/lib/` 経由で参照する lib 名の推移閉包を返す。

    hooks: {hook ファイル名: 内容}。libs: {lib ファイル名: 内容}（利用可能な lib 全部）。
    lib が別の lib を参照する場合も辿る。コメント行（`#` 始まり）は参照と見なさない。
    参照先が libs に無ければ ValueError（配布物が hook の前提を満たせないので fail fast。
    2026-08-05 に opencode で review-gate.sh の配布漏れが「共有ライブラリが読めません」
    として全 Bash の deny になった）。
    """

    def refs(data: bytes) -> list[str]:
        found: set[str] = set()
        for line in data.decode("utf-8", errors="replace").splitlines():
            if line.lstrip().startswith("#"):
                continue
            found.update(HOOK_LIB_REF.findall(line))
        return sorted(found)

    closure: set[str] = set()
    queue: list[tuple[str, str]] = [
        (hook_name, lib_name)
        for hook_name, data in sorted(hooks.items())
        for lib_name in refs(data)
    ]
    while queue:
        referrer, lib_name = queue.pop(0)
        if lib_name in closure:
            continue
        if lib_name not in libs:
            raise ValueError(
                f"{referrer} が参照する lib/{lib_name} が lib source にありません"
            )
        closure.add(lib_name)
        queue.extend((lib_name, nested) for nested in refs(libs[lib_name]))
    return closure


def _hook_files_under(files: dict[str, bytes], parent: str) -> dict[str, bytes]:
    """manifest files のうち parent 直下（サブディレクトリを含まない）のファイルを返す。"""
    return {
        rel[len(parent):]: data
        for rel, data in files.items()
        if rel.startswith(parent) and "/" not in rel[len(parent):]
    }


def _validate_curated_completeness(repo: Path, curated_root: Path, dest_key: str) -> None:
    """rulesync.lock 宣言 skill が curated_root に揃っているか検証する（ADR-011 fail-closed）。

    ディレクトリ自体が無い場合（rulesync 未実行）は呼び出し元が skip するため、ここに
    来るのは「取得済みだが lock とズレている」ケースのみ。
    """
    names = list_curated_skills(repo)
    invalid = invalid_skill_names(names)
    if invalid:
        raise ValueError(
            "rulesync.lock に安全でない skill 名が含まれています: "
            + ", ".join(invalid) + f"（{dest_key} の source）"
        )
    missing = sorted(name for name in names if not (curated_root / name).is_dir())
    if missing:
        raise ValueError(
            f"rulesync.lock に宣言された skill が {CURATED_SKILLS_SOURCE}/ にありません: "
            + ", ".join(missing)
            + f"（{dest_key} の source）。rulesync install --frozen を確認してください"
        )


@dataclass
class Manifest:
    """配布期待値のマップ。

    files: {相対パス文字列: bytes}
    warnings: 警告メッセージのリスト（skip された source 等）
    incomplete_dests: source の一部が skip され全容が不明な dest_key の集合
                      （--prune がこの dest を削除対象から除外するために使う）
    disabled_plugin_files: disabledPlugins により files から除外された相対パスの集合
                            （--push の dry-run 表示用。--prune ではここに入る
                            = files に無い = 管理対象外として削除される）
    """
    files: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    incomplete_dests: set = field(default_factory=set)
    disabled_plugin_files: set = field(default_factory=set)


@dataclass
class Drift:
    """live との差分の1件。"""
    path: str
    kind: str  # "missing" | "changed" | "mode" | "obsolete" | "unreconciled" ほか


def requires_executable(rel: str, cfg: dict) -> bool:
    """dest 相対パスが live 側で実行ビットを必要とするか。

    hook / script は settings.json 等から直接起動されるため .sh / .py を対象にし、
    拡張子を持たない実行物は target config の "executables" で明示宣言する。
    """
    return rel.endswith((".sh", ".py")) or rel in cfg.get("executables", [])


def lacks_exec_bit(mode: int | None) -> bool:
    """観測した mode が owner の実行ビットを欠いているか。

    mode は symlink を辿った stat の値（実際に起動できるか＝参照先の mode）で
    判定する。symlink に chmod を当てるかは呼び出し側の判断で、ここは検出のみ。
    mode が観測できなかった（None）場合は「欠いている」とは言えないので False。
    """
    return mode is not None and not mode & stat.S_IXUSR


def uninitialized_submodule_paths(repo: Path) -> list[str]:
    """`.gitmodules` に宣言されているが中身が空（未取得）の submodule パスリスト。"""
    gitmodules = repo / ".gitmodules"
    if not gitmodules.is_file():
        return []
    paths = re.findall(
        r"^\s*path\s*=\s*(\S+)", gitmodules.read_text(encoding="utf-8"), re.MULTILINE
    )
    return [
        p
        for p in paths
        if not (repo / p).is_dir() or not any((repo / p).iterdir())
    ]


def in_uninitialized_submodule(rel: str, uninit_submodules: list[str]) -> bool:
    """repo 相対パス rel が未取得 submodule の配下か。

    .gitmodules の path は末尾 '/' の有無が揺れるため rstrip して前方一致で見る。
    判定を 1 箇所に置き、resolver / distribution_state / validator で同じ結果に揃える。
    """
    return any(rel.startswith(sub.rstrip("/")) for sub in uninit_submodules)


def find_spec_for_path(distribute: dict, path: str) -> tuple[str, dict] | None:
    """配布先 path を所有する distribute entry を返す。"""
    if path in distribute:
        return path, distribute[path]
    for key, spec in distribute.items():
        if key.endswith("/") and path.startswith(key):
            return key, spec
    return None


def resolve_pull_source(
    sources: list, candidate_path, uninit_submodules: list
) -> tuple[str | None, list, list]:
    """後勝ちの source precedence と incomplete source safety から pull 先を決める。

    submodule 未取得で実在チェックができない source があると誤った書き戻し先を
    選びうるため、winning_source=None を返す（呼び出し元は blocking を見て skip する）。
    """
    blocking = [source for source in sources if in_uninitialized_submodule(source, uninit_submodules)]
    if blocking:
        return None, [], blocking

    existing_sources = [source for source in sources if candidate_path(source).exists()]
    winning_source = existing_sources[-1] if existing_sources else sources[0]
    return winning_source, existing_sources, []


def _is_disabled_plugin(rel: str, disabled_plugins: set) -> bool:
    """dest 相対パスが disabledPlugins で無効化された plugin ファイルか判定する。

    plugins/ 配下で、拡張子を除いたファイル名（stem）が disabledPlugins に
    含まれる場合に True。
    """
    return rel.startswith("plugins/") and Path(rel).stem in disabled_plugins


def _core_disabled_skills(target_name: str, repo: Path) -> set:
    """core 側の disabled-skills.json から対象ターゲットの無効化 skill 名を返す。

    codex/omp など複数 target でほぼ同一の disabledSkills を持つ場合、
    共通部を packages/core/disabled-skills.json の "common" に集約し、
    target 固有差分だけを各 target キーに残すための一元化機構。
    ファイル内の "targets" に明示された target にのみ common + target キーを
    マージする（claude のように全 skill を配布する target を
    誤って対象にすると skill が消えて挙動が変わるため、暗黙の全 target 適用はしない）。
    ファイルが無ければ空（extras 版と同じ防御）。
    """
    path = repo / "packages" / "core" / "disabled-skills.json"
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if target_name not in set(data.get("targets", [])):
        return set()
    return set(data.get("common", [])) | set(data.get(target_name, []))


def _extras_disabled_skills(target_name: str, repo: Path) -> set:
    """extras 側の disabled-skills.json から対象ターゲットの無効化 skill 名を返す。

    会社・プロジェクト固有名を含む skill は public の config.json に書けない
    （pre-commit の禁止語ガード）ため、private submodule 側の
    packages/extras/_active/disabled-skills.json（{target名: [skill名, ...]}）
    で宣言し、_core_disabled_skills() の結果とマージする。
    ファイルが無ければ空（extras 未取得の環境でもエラーにしない）。
    """
    path = repo / "packages" / "extras" / "_active" / "disabled-skills.json"
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get(target_name, []))


def disabled_skills(target_name: str, repo: Path) -> set:
    """core + extras の disabled-skills.json を合成した無効化 skill 名の集合。"""
    return _core_disabled_skills(target_name, repo) | _extras_disabled_skills(target_name, repo)


def _is_disabled_skill(rel: str, disabled: set) -> bool:
    """dest 相対パスが disabledSkills で無効化された skill 配下か判定する。

    skills/<name>/... の <name>（skill ディレクトリ名）が disabledSkills に
    含まれる場合に True。ターゲットで機能しない skill（例: omp での MCP 依存
    skill）を配布から除外するために使う。
    """
    parts = Path(rel).parts
    return len(parts) >= 2 and parts[0] == "skills" and parts[1] in disabled


def _collect_dir(src: Path, warnings: list) -> dict[str, bytes]:
    """src ディレクトリを再帰的に走査し、{相対パス: bytes} を返す。

    .DS_Store と __pycache__ 配下（Python コンパイル済みキャッシュ）は除外する。
    symlink（ファイル symlink・リンク切れとも）は無警告でデリファレンス/欠落させず、
    warnings に記録して配布から除外する。
    """
    result: dict[str, bytes] = {}
    for child in src.rglob("*"):
        if child.is_symlink():
            rel = child.relative_to(src).as_posix()
            warnings.append(f"symlink は配布しない: {src / rel}")
            continue
        if not child.is_file():
            continue
        if child.name == ".DS_Store":
            continue
        rel = child.relative_to(src)
        if "__pycache__" in rel.parts:
            continue
        result[rel.as_posix()] = child.read_bytes()
    return result


def _resolve_source_files(
    sources: list,
    repo: Path,
    uninit_submodules: list,
    dest_key: str,
    warnings: list,
) -> tuple[dict[str, bytes], bool]:
    """sources（文字列リスト）を順に処理し、後勝ちで合成した
    ({相対パス: bytes}, source が skip され全容不明か) を返す。

    source が存在しない場合:
      - gitmodules 宣言済みかつ未取得 submodule 配下 → skip（warnings に記録、incomplete=True）
      - それ以外 → FileNotFoundError（fail fast）
    source の実体が symlink（ファイル・ディレクトリとも）なら拒否する。_collect_dir が
    配下の symlink を配らないのと同じ理由で、root が symlink だと repo 外の内容が
    配布物に埋め込まれる経路になる。
    1 つの dest に file source と directory source を混在させると片方が黙って
    捨てられる（file dest は "" キーしか採用しない）ため、混在も拒否する。
    """
    merged: dict[str, bytes] = {}
    incomplete = False
    kinds: set[str] = set()

    for src_rel in sources:
        src_path = repo / src_rel
        is_curated_source = src_rel.rstrip("/") == CURATED_SKILLS_SOURCE
        if src_path.is_symlink():
            raise ValueError(
                f"source が symlink です（配布しない）: {src_rel}（{dest_key} の source）"
            )
        if not src_path.exists():
            if is_curated_source:
                warnings.append(
                    f"rulesync 未取得のため skip: {src_rel}（{dest_key} の source）"
                )
                incomplete = True
                continue
            if in_uninitialized_submodule(src_rel, uninit_submodules):
                warnings.append(
                    f"submodule 未取得のため skip: {src_rel}（{dest_key} の source）"
                )
                incomplete = True
                continue
            raise FileNotFoundError(
                f"source が存在しません: {src_rel}（{dest_key} の source）"
            )

        if is_curated_source:
            _validate_curated_completeness(repo, src_path, dest_key)

        if src_path.is_file():
            kinds.add("file")
            # 単一ファイル → dest_key そのものが宛先
            merged[""] = src_path.read_bytes()
        elif src_path.is_dir():
            kinds.add("dir")
            # ディレクトリ → 再帰収集。後勝ちで上書き
            collected = _collect_dir(src_path, warnings)
            if is_curated_source:
                # rulesync.jsonc から外した skill の残骸（ref 不変だと rulesync が prune
                # しない）を配らないよう、lock 宣言分だけに絞る。
                declared = list_curated_skills(repo)
                collected = {
                    rel: data
                    for rel, data in collected.items()
                    if rel.split("/", 1)[0] in declared
                }
            for rel, data in collected.items():
                merged[rel] = data

    if len(kinds) > 1:
        raise ValueError(
            f"distribute[{dest_key!r}] の source にファイルとディレクトリが混在しています: {sources!r}"
        )
    return merged, incomplete


def _apply_skill_overrides_to_manifest(
    repo: Path, cfg: dict, result: Manifest
) -> None:
    """extras の skill override を配布期待値へ合成する。

    skill override は push 後の副作用にせず Manifest の bytes に含める。
    これにより check と distribution ledger も、実際に live へ書かれる内容を
    同じ resolved state として扱える。
    """
    if not cfg.get("extrasOverlay"):
        return

    extras_base = repo / "packages" / "extras"
    if not extras_base.is_dir():
        return

    distributed_skills = {
        Path(rel).parts[1]
        for rel in result.files
        if len(Path(rel).parts) >= 2 and Path(rel).parts[0] == _SKILLS_DEST.rstrip("/")
    }

    for extra in sorted(extras_base.iterdir()):
        override_root = extra / "skill-overrides"
        if not override_root.is_dir():
            continue
        for override_skill_dir in sorted(override_root.iterdir()):
            if not override_skill_dir.is_dir():
                continue
            skill_name = override_skill_dir.name
            if skill_name not in distributed_skills:
                result.warnings.append(
                    f"skill override を skip（対象 skill が manifest にありません）: {skill_name}"
                )
                continue
            for override_file in sorted(override_skill_dir.iterdir()):
                if not override_file.is_file() or override_file.name == ".DS_Store":
                    continue
                rel = f"skills/{skill_name}/{override_file.name}"
                safe_relative(rel, "skill override", base=repo)
                result.files[rel] = override_file.read_bytes()


def manifest(target_name: str, repo: Path, cfg: dict | None = None) -> Manifest:
    """distribute 宣言を解決し、「相対パス → 期待内容（bytes）」の Manifest を返す。

    Args:
        target_name: ターゲット名（例: codex, opencode, claude）
        repo: リポジトリルート
        cfg: 読み込み済みの target config。省略時は load_target で読む
             （呼び出し元が既に読んでいる場合の二重読み防止）

    Returns:
        Manifest（files / warnings / disabled_plugin_files）
    """
    if cfg is None:
        cfg = load_target(target_name, repo)
    distribute: dict = cfg.get("distribute", {})
    skills_transform: dict = cfg.get("skillsTransform", {})
    keep_fields: set = set(skills_transform.get("keepFrontmatterFields", []))
    disabled_plugins: set = set(cfg.get("disabledPlugins", []))
    disabled = disabled_skills(target_name, repo)

    uninit_submodules = uninitialized_submodule_paths(repo)
    result = Manifest()
    # hookLibClosure の dest は、親ディレクトリに配る hook 群が出揃ってから解決する
    deferred_lib_closures: list[tuple[str, dict[str, bytes]]] = []

    for dest_key, spec in distribute.items():
        # dest_key は配布先相対。ここでの目的は字面検査（絶対パス・'..'）で、
        # 配布先での symlink 実体は distribution_state の ledger guard が見る
        safe_relative(dest_key, "dest_key", base=repo)

        if not isinstance(spec, dict):
            result.warnings.append(f"distribute[{dest_key!r}] のスペックが dict でありません: skip")
            continue

        source = spec.get("source")
        if source is None:
            result.warnings.append(f"distribute[{dest_key!r}] に source がありません: skip")
            continue

        expand_includes_flag: bool = spec.get("expandIncludes", False)
        has_transform: bool = bool(spec.get("transform"))
        lib_closure_flag: bool = spec.get("hookLibClosure", False)
        is_dir_dest: bool = dest_key.endswith("/")
        # hook は `$HOOK_DIR/lib/<name>.sh` を読むので宛先の末尾は必ず `lib/`。
        # `libs/` 等のタイポを通すと lib が別名で配られ、fail-closed な guard が全 Bash を deny する
        if lib_closure_flag and (
            not is_dir_dest
            or dest_key.count("/") < 2
            or dest_key.rstrip("/").rsplit("/", 1)[-1] != "lib"
        ):
            raise ValueError(
                f"{target_name}: distribute[{dest_key!r}] の hookLibClosure は"
                f" `<hooks dir>/lib/` 形式のディレクトリ宛てにだけ指定できます"
            )

        # sources を正規化（文字列 or リスト → リスト）
        sources: list = source if isinstance(source, list) else [source]
        for s in sources:
            safe_relative(s, f"source（{dest_key}）", base=repo)
        # source ファイル群を収集（後勝ちで合成）
        raw_files, incomplete = _resolve_source_files(
            sources, repo, uninit_submodules, dest_key, result.warnings
        )
        if incomplete:
            result.incomplete_dests.add(dest_key)

        if not raw_files:
            # すべて skip されたか空ディレクトリ
            continue

        if is_dir_dest and "" in raw_files:
            raise ValueError(
                f"{target_name}: distribute[{dest_key!r}] はディレクトリ宛て（末尾 '/'）ですが"
                f" source の実体はファイルです: {sources!r}"
            )
        if not is_dir_dest and "" not in raw_files:
            raise ValueError(
                f"{target_name}: distribute[{dest_key!r}] はファイル宛てですが"
                f" source の実体はディレクトリです: {sources!r}"
            )

        if not is_dir_dest:
            # 単一ファイル宛て
            if _is_disabled_plugin(dest_key, disabled_plugins):
                result.disabled_plugin_files.add(dest_key)
                continue

            data = raw_files[""]
            if expand_includes_flag:
                # テンプレートの include ディレクティブを fragment で展開
                data = expand_includes(data.decode("utf-8"), repo).encode("utf-8")
            result.files[dest_key] = data
            continue

        if lib_closure_flag:
            deferred_lib_closures.append((dest_key, raw_files))
            continue

        # ディレクトリ宛て（dest_key は "/" 終わり）
        for rel, data in raw_files.items():
            dest_rel = dest_key + rel  # 例: "skills/demo-skill/SKILL.md"

            if (
                _is_disabled_plugin(dest_rel, disabled_plugins)
                or _is_disabled_skill(dest_rel, disabled)
            ):
                result.disabled_plugin_files.add(dest_rel)
                continue

            if has_transform and rel.endswith("/SKILL.md"):
                # frontmatter 変換（SKILL.md のみ）
                data = transform_skill_md(data.decode("utf-8"), keep_fields).encode("utf-8")

            result.files[dest_rel] = data

    for dest_key, libs in deferred_lib_closures:
        parent = dest_key.rstrip("/").rsplit("/", 1)[0] + "/"
        hooks = _hook_files_under(result.files, parent)
        if not hooks:
            raise ValueError(
                f"{target_name}: distribute[{dest_key!r}] の hookLibClosure が参照する"
                f" hook が {parent} に配布されていません"
            )
        try:
            closure = hook_lib_closure(hooks, libs)
        except ValueError as exc:
            raise ValueError(f"{target_name}: distribute[{dest_key!r}]: {exc}") from exc
        for lib_name in sorted(closure):
            result.files[dest_key + lib_name] = libs[lib_name]

    _apply_skill_overrides_to_manifest(repo, cfg, result)
    return result
