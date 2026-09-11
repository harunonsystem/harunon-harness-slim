"""harness_lib.settings_sync — settingsSync 宣言の configFile を 1 つの論理ドキュメントとして合成する。

公開 interface は 2 つ:

- compose(cfg, repo, live_dir, reader) -> ComposedSettings | None
    live の configFile に「template seed（無ければ）→ SSOT keys（+ removeKeys）→
    local / extras overlay」を順に重ねた結果と、段ごとの変更集合を返す。
- drifts(cfg, repo, live_dir, reader) -> list[Drift]
    同じ層の並びを live と比較して drift を返す（checkOnlyKeys / extrasOverlay 値の
    検査を含む）。

どちらも層の並びを _layers 1 か所から取る。合成順序の知識をここ以外に持たないことで
--check と --push がずれない。フォーマット差（toml/yaml/json）、dotted key、computed
overlay（danger-rules の permission glob、disabled-skills の ignore）はすべて内部。

live（配布先）への書き込みは distribution_state の plan/apply が担う。ここは純粋な計算
だけを持ち、配布先の読み取りは LiveReader 経由で行う（plan 側が注入した filesystem
adapter と同じ観測を使い、host Path 直読みの別実装を持たない）。
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import danger_rules
from .merge import merge_overlay_into_settings
from . import resolver
from .paths import relative_name, safe_relative
from .resolver import Drift


class LiveReader(Protocol):
    """配布先ファイルの観測 seam。"""

    def is_file(self, path: Path) -> bool: ...

    def read_text(self, path: Path) -> str: ...


class HostReader:
    """本番の配布先読み取り（pathlib 直読み）。"""

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")


HOST_READER = HostReader()


@dataclass(frozen=True)
class SettingsChange:
    """settings-sync / settings-overlay の 1 段が同期した dotted key の集合。"""

    label: str
    changed: tuple[str, ...]
    removed: tuple[str, ...] = ()


@dataclass(frozen=True)
class SettingsStep:
    """compose の 1 段。kind は plan の operation 種別と同じ語彙。

    - settings-template: configFile が無かったので template（計算 overlay 込み）を seed した
    - settings-sync:     SSOT keys（+ removeKeys）を同期した
    - settings-overlay:  local / extras overlay の keys を同期した（change.label が種別）
    text はこの段を適用した後の configFile 全文。
    """

    kind: str
    source_rel: str
    text: str
    change: SettingsChange


@dataclass(frozen=True)
class ComposedSettings:
    """compose の結果。steps は変更があった段だけ（順序は適用順）。text は最終テキスト。"""

    config_file: str
    seeded: bool
    steps: tuple[SettingsStep, ...]
    text: str


@dataclass(frozen=True)
class _Layer:
    """合成の 1 層。expected の keys を live に同期し、removals を live から消す。"""

    kind: str
    label: str
    source_rel: str
    expected: dict
    keys: tuple[str, ...]
    removals: tuple[str, ...]


@dataclass(frozen=True)
class SettingsTemplate:
    """settingsSync 宣言を解決した結果（SSOT テンプレート + 計算 overlay）。

    template は computedGlobs / computedSkillIgnores を適用済み。
    extras_overlay_values は extrasOverlay（env.json / settings-overlay.json）の最終値を
    dotted key で持ち、checkOnlyKeys の判定と drift 判定に使う。
    """

    source_rel: str
    keys: tuple[str, ...]
    settings_format: str
    config_file: str
    template_text: str
    template: dict
    extras_overlay_values: dict[str, object]


def _settings_sync_spec(cfg: dict, repo: Path) -> tuple[str, list, str] | None:
    """settingsSync 宣言を (source 相対パス, keys, format) に解決する。宣言が無ければ None。

    source は repo 相対でなければならない。検証しないと `../..` や絶対パスで repo 外を
    読み、その値を live へ同期できる（2026-07-26 に実測）。
    """
    spec = cfg.get("settingsSync")
    if not spec:
        return None
    source = safe_relative(spec["source"], "settingsSync.source", base=repo)
    return source, spec["keys"], spec.get("format", "json")


def _validate_settings_sync_paths(cfg: dict, repo: Path) -> None:
    """settingsSync 関連の cfg 由来パスが repo / dest 内に閉じていることを検証する。

    configFile は dest_dir と join されるため '../' や絶対パスを許すと dest 外への
    書き込みが可能になる（字面検査。live 側の symlink は正当な状態なので実体は見ない）。
    source 系（source/localSource/extrasSource/computedGlobs.table）は repo と join
    されるため、symlink の実体まで含めて repo 外読み出しを防ぐ。
    """
    relative_name(cfg["configFile"], "configFile")
    spec = cfg.get("settingsSync")
    if not spec:
        return
    safe_relative(spec["source"], "settingsSync.source", base=repo)
    for key, label in (
        ("localSource", "settingsSync.localSource"),
        ("extrasSource", "settingsSync.extrasSource"),
    ):
        value = spec.get(key)
        if value:
            safe_relative(value, label, base=repo)
    computed_globs = spec.get("computedGlobs")
    if computed_globs:
        safe_relative(computed_globs["table"], "settingsSync.computedGlobs.table", base=repo)
    computed_features = spec.get("computedFeatures")
    if computed_features:
        safe_relative(
            computed_features["table"], "settingsSync.computedFeatures.table", base=repo,
        )


def _settings_sync_computed_globs_spec(cfg: dict) -> dict | None:
    """settingsSync.computedGlobs 宣言を返す（無ければ None）。

    danger-rules.json（危険コマンドルール SSOT）の permission glob を「計算された
    overlay 層」として template にマージするための宣言。local/extras overlay と違い
    ソースはファイルではなく danger_rules.permission_globs() の計算結果。
    """
    spec = cfg.get("settingsSync")
    if not spec:
        return None
    return spec.get("computedGlobs")


def _computed_features_spec(cfg: dict) -> dict | None:
    """settingsSync.computedFeatures 宣言を返す（無ければ None）。

    codex の [features] に何を書き何を live から撤去するかは packages/targets/codex/
    features.json が SSOT。keys / removeKeys に features.* を二重に列挙しないための宣言。
    """
    spec = cfg.get("settingsSync")
    if not spec:
        return None
    return spec.get("computedFeatures")


def _computed_feature_keys(cfg: dict, repo: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """computedFeatures の table から (同期する dotted key, 撤去する dotted key) を導出する。

    declare が true のフラグは keys 側、false のフラグは removeKeys 側に落ちる。宣言が
    無ければ両方空タプル。table には declare false のフラグも載るため、「default と同値
    だから書かない」という判断が理由（why）付きで 1 か所に残る。
    """
    spec = _computed_features_spec(cfg)
    if not spec:
        return (), ()
    table_rel = safe_relative(spec["table"], "settingsSync.computedFeatures.table", base=repo)
    features = json.loads((repo / table_rel).read_text(encoding="utf-8"))["features"]
    prefix = spec["prefix"]
    declared = tuple(f"{prefix}.{name}" for name, entry in features.items() if entry["declare"])
    retired = tuple(f"{prefix}.{name}" for name, entry in features.items() if not entry["declare"])
    return declared, retired


def _merge_ordered_patterns(existing: list, computed: dict) -> None:
    """computed（glob -> "deny"|"prompt"）を existing（[{match, approval}, ...]）へ
    先頭側に deny → prompt の順でマージする（in-place, 冪等）。

    omp の bash.patterns は first-match-wins の順序付き配列なので、danger-rules
    由来の deny/prompt は既存の（computed 以外の）パターンより前に置く。broad な
    prompt（例: "git push *"）が narrower な deny（例: "git push --force*"）より
    先に来ると deny が食われてしまうため、deny は prompt よりもさらに前に置く。
    並びは table の rules 配列順（computed の dict 挿入順）で決定的。

    同じ (match, approval) を持つ既存要素は一旦取り除いてから再構成するため、
    同じ computed で複数回呼んでもリストは増殖しない。
    """
    computed_pairs = {(glob, tier) for glob, tier in computed.items()}
    remaining = [
        entry for entry in existing
        if not (isinstance(entry, dict) and (entry.get("match"), entry.get("approval")) in computed_pairs)
    ]
    ordered = [
        {"match": glob, "approval": tier}
        for tier in ("deny", "prompt")
        for glob, glob_tier in computed.items()
        if glob_tier == tier
    ]
    existing[:] = ordered + remaining


def _merge_computed_globs(template: dict, merge_key: str, merge_shape: str, computed: dict) -> None:
    """computed（glob -> tier）を template の merge_key 位置にマージする（in-place）。

    mergeShape で対象の構造を明示する（target 名では分岐しない）:
    - "flat":           mergeKey は glob -> action のフラットな dict（opencode の
                        permission.bash）。computed をそのまま dict.update する。
    - "orderedPatterns": mergeKey は {match, approval} の順序付きリスト（omp の
                        bash.patterns）。_merge_ordered_patterns に委譲する。

    旧 "tiered"（action -> glob リストの dict = 旧 omp の permissions.bash）は
    omp の bash.patterns 移行で消費者ゼロになったため廃止した。
    """
    parts = merge_key.split(".")
    cursor = template
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    leaf_key = parts[-1]

    if merge_shape == "orderedPatterns":
        existing_list = cursor.setdefault(leaf_key, [])
        _merge_ordered_patterns(existing_list, computed)
        return

    if merge_shape == "flat":
        cursor.setdefault(leaf_key, {}).update(computed)
        return

    raise ValueError(f"未知の mergeShape です: {merge_shape!r}")


def _apply_computed_globs(cfg: dict, repo: Path, template: dict) -> None:
    """settingsSync.computedGlobs 宣言に従い、danger-rules.json の permission globs を
    template に計算 overlay としてマージする（in-place）。宣言が無ければ何もしない。
    """
    spec = _settings_sync_computed_globs_spec(cfg)
    if not spec:
        return
    table_rel = safe_relative(spec["table"], "settingsSync.computedGlobs.table", base=repo)
    table = json.loads((repo / table_rel).read_text(encoding="utf-8"))
    computed = danger_rules.permission_globs(table, spec["target"])
    _merge_computed_globs(template, spec["mergeKey"], spec["mergeShape"], computed)


def _apply_computed_skill_ignores(cfg: dict, repo: Path, template: dict) -> None:
    """settingsSync.computedSkillIgnores 宣言に従い、disabled-skills.json の無効化
    skill 名を template の mergeKey（リスト）へ計算 overlay としてマージする（in-place）。

    配布層で skill を配らないだけでは無効化にならないツール向け。omp は
    ~/.agents/skills（shared-agents target の配布先）も読むため、自 configDir に
    配らなくても skill が見えてしまう。実際に隠すにはツール側の設定で
    宣言する必要があり、その値の SSOT は disabled-skills.json のままにする。
    """
    spec = cfg.get("settingsSync", {}).get("computedSkillIgnores")
    if not spec:
        return
    computed = sorted(resolver.disabled_skills(spec["target"], repo))
    parts = spec["mergeKey"].split(".")
    cursor = template
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    existing = cursor.setdefault(parts[-1], [])
    for name in computed:
        if name not in existing:
            existing.append(name)


def _settings_sync_overlay_specs(cfg: dict, repo: Path) -> list[tuple[str, str, list]]:
    """overlay 宣言を [(label, source 相対パス, keys)] に解決する。

    overlay は SSOT keys と同じ同期・drift 意味論を持つが、source ファイルが
    不在なら黙ってスキップされる（エラーにしない）:
    - local  (localSource / localKeys):   マシン固有値。gitignore されたファイル
    - extras (extrasSource / extrasKeys): 会社・契約固有値。private submodule 内
      のファイル（CI では submodule 未取得のため不在になる）
    source と keys の両方が宣言されたペアのみ返す。
    """
    spec = cfg.get("settingsSync")
    if not spec:
        return []
    overlays = []
    for label, source_key, keys_key in (
        ("local", "localSource", "localKeys"),
        ("extras", "extrasSource", "extrasKeys"),
    ):
        source = spec.get(source_key)
        keys = spec.get(keys_key)
        if source and keys:
            overlays.append((label, safe_relative(source, f"settingsSync.{source_key}", base=repo), keys))
    return overlays


def extras_overlay_sources(cfg: dict, repo: Path) -> list[tuple[str, str, dict]]:
    """extrasOverlay 宣言に対応する JSON overlay を決定順で読む。

    Returns: [(extra 名, overlay ファイル名, overlay 内容)]
    """
    if not cfg.get("extrasOverlay"):
        return []
    extras_base = repo / "packages" / "extras"
    if not extras_base.is_dir():
        return []

    overlays: list[tuple[str, str, dict]] = []
    for extra in sorted(extras_base.iterdir()):
        if not extra.is_dir():
            continue
        for overlay_name in ("env.json", "settings-overlay.json"):
            overlay_path = extra / overlay_name
            if not overlay_path.is_file():
                continue
            overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
            if not isinstance(overlay, dict):
                raise ValueError(f"extras overlay は object でなければなりません: {overlay_path}")
            overlays.append((extra.name, overlay_name, overlay))
    return overlays


def _flatten_overlay_values(data: dict, prefix: str = "") -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if value:
                values.update(_flatten_overlay_values(value, dotted))
            else:
                values[dotted] = value
        else:
            values[dotted] = value
    return values


def _extras_overlay_values(cfg: dict, repo: Path) -> dict[str, object]:
    """extras overlay の最終値を dotted key へ解決する。"""
    merged: dict = {}
    for _extra, overlay_name, overlay in extras_overlay_sources(cfg, repo):
        merge_overlay_into_settings(merged, overlay, overlay_name)
    return _flatten_overlay_values(merged)


def _overlay_manages_key(key: str, overlay_values: dict[str, object]) -> bool:
    return any(
        overlay_key == key or overlay_key.startswith(f"{key}.")
        for overlay_key in overlay_values
    )


def _get_dotted(data: dict, dotted_key: str):
    cursor = data
    for part in dotted_key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def _set_dotted(data: dict, dotted_key: str, value) -> None:
    """ネストされた辞書にドット区切りキーで値を設定する。"""
    parts = dotted_key.split(".")
    cursor = data
    for part in parts[:-1]:
        if part not in cursor:
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def _delete_dotted(data: dict, dotted_key: str) -> bool:
    """Delete a dotted key. Return whether a value was removed."""
    parts = dotted_key.split(".")
    cursor = data
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            return False
        cursor = cursor[part]
    if not isinstance(cursor, dict) or parts[-1] not in cursor:
        return False
    del cursor[parts[-1]]
    return True


class _JsonSettingsAdapter:
    def parse(self, text: str) -> dict:
        return json.loads(text)

    def render(self, live_text: str, live_data: dict, updates: dict, removals: tuple) -> str:
        for key, value in updates.items():
            _set_dotted(live_data, key, value)
        for key in removals:
            _delete_dotted(live_data, key)
        return json.dumps(live_data, ensure_ascii=False, indent=2) + "\n"


class _TomlSettingsAdapter:
    def parse(self, text: str) -> dict:
        return tomllib.loads(text)

    def render(self, live_text: str, live_data: dict, updates: dict, removals: tuple) -> str:
        updated_text = live_text
        for key, value in updates.items():
            updated_text = _replace_toml_key(updated_text, key, value)
        for key in removals:
            updated_text = _remove_toml_key(updated_text, key)
        return updated_text


class _YamlSettingsAdapter:
    def parse(self, text: str) -> dict:
        import yaml
        return yaml.safe_load(text)

    def render(self, live_text: str, live_data: dict, updates: dict, removals: tuple) -> str:
        import yaml
        for key, value in updates.items():
            _set_dotted(live_data, key, value)
        for key in removals:
            _delete_dotted(live_data, key)
        return yaml.safe_dump(
            live_data, allow_unicode=True, sort_keys=False, default_flow_style=False,
        )


_SETTINGS_ADAPTERS = {
    "json": _JsonSettingsAdapter(),
    "toml": _TomlSettingsAdapter(),
    "yaml": _YamlSettingsAdapter(),
}


def _settings_adapter(settings_format: str):
    """settings format の差分を担当する adapter を返す。

    未知の format は宣言側の誤りなので例外にする（JSON へ黙って倒すと TOML を JSON
    として読んで全キーが drift 扱いになり、原因が見えない）。
    """
    try:
        return _SETTINGS_ADAPTERS[settings_format]
    except KeyError:
        raise ValueError(
            f"未知の settingsSync.format です: {settings_format!r}"
            f"（{', '.join(sorted(_SETTINGS_ADAPTERS))} のいずれか）"
        ) from None


def _format_toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        items = ", ".join(f"{k} = {_format_toml_value(v)}" for k, v in value.items())
        return "{ " + items + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(v) for v in value) + "]"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


def _drop_toml_table(lines: list[str], dotted_key: str) -> list[str]:
    """dotted_key を名前に持つテーブル宣言を、その子孫テーブルごと取り除いた行を返す。"""
    own_header = f"[{dotted_key}]"
    child_prefix = f"[{dotted_key}."
    kept: list[str] = []
    dropping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            dropping = stripped == own_header or stripped.startswith(child_prefix)
        if not dropping:
            kept.append(line)
    return kept


def _replace_toml_key(text: str, dotted_key: str, value) -> str:
    parts = dotted_key.split(".")
    section = ".".join(parts[:-1])
    key = parts[-1]

    # A table-valued dotted key (for example features.multi_agent_v2) must be
    # written as a TOML section.  Writing the dict as an inline table makes
    # Codex interpret the feature name as a boolean flag.
    if isinstance(value, dict):
        table_header = f"[{dotted_key}]"
        lines = text.splitlines()

        # Migrate an older inline-table declaration in the parent section
        # before creating the dedicated table; TOML rejects both declarations.
        parent_header = f"[{section}]"
        parent_start = next(
            (i for i, line in enumerate(lines) if line.strip() == parent_header),
            -1,
        )
        if parent_start != -1:
            parent_end = next(
                (i for i in range(parent_start + 1, len(lines))
                 if lines[i].strip().startswith("[") and lines[i].strip().endswith("]")),
                len(lines),
            )
            lines[parent_start + 1:parent_end] = [
                line for line in lines[parent_start + 1:parent_end]
                if line.split("=", 1)[0].strip() != key
            ]

        start = next((i for i, line in enumerate(lines) if line.strip() == table_header), -1)
        rendered = [table_header] + [
            f"{name} = {_format_toml_value(item)}" for name, item in value.items()
        ]
        if start == -1:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(rendered)
        else:
            end = next(
                (i for i in range(start + 1, len(lines))
                 if lines[i].strip().startswith("[") and lines[i].strip().endswith("]")),
                len(lines),
            )
            lines[start:end] = rendered
        return "\n".join(lines) + "\n"

    replacement = f"{key} = {_format_toml_value(value)}"
    # 同名の子テーブル（例: 旧宣言の [features.context_management]）が残ったまま
    # スカラーを書くと、TOML が同じキーを二重定義して Codex が
    # "Cannot overwrite a value" で config 全体を読めなくなる。先に畳む。
    lines = _drop_toml_table(text.splitlines(), dotted_key)

    start = 0
    end = len(lines)
    if section:
        header = f"[{section}]"
        start = -1
        for i, line in enumerate(lines):
            if line.strip() == header:
                start = i + 1
                break
        if start == -1:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend([header, replacement])
            return "\n".join(lines) + "\n"
        for i in range(start, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                end = i
                break
    else:
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                end = i
                break

    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        existing_key = stripped.split("=", 1)[0].strip()
        if existing_key == key:
            prefix = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
            replace_end = i + 1
            current_value = stripped.split("=", 1)[1].strip()
            if current_value.startswith("[") and not current_value.endswith("]"):
                while replace_end < end:
                    if lines[replace_end].strip().endswith("]"):
                        replace_end += 1
                        break
                    replace_end += 1
            lines[i:replace_end] = [prefix + replacement]
            return "\n".join(lines) + "\n"

    lines.insert(end, replacement)
    return "\n".join(lines) + "\n"


def _remove_toml_key(text: str, dotted_key: str) -> str:
    """Remove one dotted key from an existing TOML document, preserving other text."""
    parts = dotted_key.split(".")
    section = ".".join(parts[:-1])
    key = parts[-1]
    lines = text.splitlines()
    # A retired dotted key may be a TOML table rather than an assignment.
    table_lines = _drop_toml_table(lines, dotted_key)
    if table_lines != lines:
        return "\n".join(table_lines) + "\n"

    start = 0
    end = len(lines)
    if section:
        header = f"[{section}]"
        start = next(
            (i + 1 for i, line in enumerate(lines) if line.strip() == header),
            -1,
        )
        if start == -1:
            return text
        end = next(
            (i for i in range(start, len(lines))
             if lines[i].strip().startswith("[") and lines[i].strip().endswith("]")),
            len(lines),
        )
    else:
        end = next(
            (i for i, line in enumerate(lines)
             if line.strip().startswith("[") and line.strip().endswith("]")),
            len(lines),
        )

    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        existing_key, current_value = (part.strip() for part in stripped.split("=", 1))
        if existing_key != key:
            continue
        remove_end = i + 1
        if current_value.startswith("[") and not current_value.endswith("]"):
            while remove_end < end:
                if lines[remove_end].strip().endswith("]"):
                    remove_end += 1
                    break
                remove_end += 1
        del lines[i:remove_end]
        return "\n".join(lines) + "\n"

    return text


def _parse_settings_text(text: str, settings_format: str):
    """settingsSync format に応じて設定テキストをパースする（toml/yaml/json）。

    yaml は PyYAML に依存するため、yaml format のターゲットを扱うときだけ
    遅延 import する（他ターゲットの bootstrap に PyYAML を強制しない）。
    """
    return _settings_adapter(settings_format).parse(text)


def _write_synced_config(
    live_text: str,
    live_data,
    settings_format: str,
    updates: dict,
    removals: tuple = (),
) -> str:
    """live の内容に updates（dotted-key -> 新値）・removals（dotted-key）を適用し、
    書き込み用テキストを返す。

    toml は元テキストへの差分置換（_replace_toml_key）、yaml/json は live_data を
    直接書き換えてダンプする。yaml の import はここでのみ遅延実行する（他フォーマットの
    target に PyYAML を強制しないため）。
    """
    return _settings_adapter(settings_format).render(
        live_text, live_data, updates, removals
    )


def _resolve_template(cfg: dict, repo: Path) -> SettingsTemplate | None:
    """settingsSync 宣言を解決し、計算 overlay 適用済みの SSOT テンプレートを返す。

    宣言が無ければ None。compose と drifts が同じ解決結果を使う。
    """
    spec = _settings_sync_spec(cfg, repo)
    if spec is None:
        return None
    _validate_settings_sync_paths(cfg, repo)
    source_rel, keys, settings_format = spec
    # configFile は dest 内に閉じたファイル名でなければならない。検証しないと
    # `../` で dest_dir の外へ書ける（2026-07-26 に実測）。
    config_file = relative_name(cfg["configFile"], "configFile")
    template_text = (repo / source_rel).read_text(encoding="utf-8")
    template = _parse_settings_text(template_text, settings_format)
    _apply_computed_globs(cfg, repo, template)
    _apply_computed_skill_ignores(cfg, repo, template)
    return SettingsTemplate(
        source_rel=source_rel,
        keys=tuple(keys),
        settings_format=settings_format,
        config_file=config_file,
        template_text=template_text,
        template=template,
        extras_overlay_values=_extras_overlay_values(cfg, repo),
    )


def _seeded_template_text(cfg: dict, resolved: SettingsTemplate) -> str:
    """configFile を新規作成するときに書き出すテキスト。

    computedGlobs 宣言がある場合、生 template_text には計算済み overlay が含まれない
    ため、マージ済み template を再シリアライズする。無ければ template を字面のまま置く。
    """
    if _settings_sync_computed_globs_spec(cfg):
        return _write_synced_config(
            resolved.template_text, resolved.template, resolved.settings_format, {},
        )
    return resolved.template_text


def _changed_keys(live: dict, expected: dict, keys) -> list[str]:
    """live と expected で値が異なる dotted key を宣言順に返す。"""
    return [key for key in keys if _get_dotted(live, key) != _get_dotted(expected, key)]


def _layers(cfg: dict, repo: Path, resolved: SettingsTemplate) -> tuple[_Layer, tuple[_Layer, ...]]:
    """合成順序の唯一の定義: (SSOT 層, overlay 層の並び)。

    SSOT 層は template の keys と removeKeys。computedFeatures 宣言があれば、そこから
    導出した keys / removals を足す。overlay 層は local → extras の宣言順で、
    source ファイルが不在の overlay は黙ってスキップする（local は gitignore、extras は
    CI で submodule 未取得のため不在になり得る）。compose も drifts もここから層を取る。
    """
    spec = cfg.get("settingsSync", {})
    declared, retired = _computed_feature_keys(cfg, repo)
    ssot = _Layer(
        kind="settings-sync",
        label="",
        source_rel=resolved.source_rel,
        expected=resolved.template,
        keys=resolved.keys + declared,
        removals=tuple(spec.get("removeKeys", [])) + retired,
    )
    overlays: list[_Layer] = []
    for label, overlay_source_rel, overlay_keys in _settings_sync_overlay_specs(cfg, repo):
        overlay_path = repo / overlay_source_rel
        if not overlay_path.is_file():
            continue
        overlay_data = _parse_settings_text(
            overlay_path.read_text(encoding="utf-8"), resolved.settings_format,
        )
        overlays.append(_Layer(
            kind="settings-overlay",
            label=label,
            source_rel=overlay_source_rel,
            expected=overlay_data,
            keys=tuple(overlay_keys),
            removals=(),
        ))
    return ssot, tuple(overlays)


def _apply_layer(text: str, settings_format: str, layer: _Layer) -> SettingsStep | None:
    """layer を text に同期した段を返す。変更が無ければ None。"""
    live = _parse_settings_text(text, settings_format)
    changed = _changed_keys(live, layer.expected, layer.keys)
    removed = [key for key in layer.removals if _get_dotted(live, key) is not None]
    if not changed and not removed:
        return None
    updated = _write_synced_config(
        text, live, settings_format,
        {key: _get_dotted(layer.expected, key) for key in changed},
        tuple(removed),
    )
    return SettingsStep(
        kind=layer.kind,
        source_rel=layer.source_rel,
        text=updated,
        change=SettingsChange(layer.label, tuple(changed), tuple(removed)),
    )


def compose(
    cfg: dict, repo: Path, live_dir: Path, reader: LiveReader = HOST_READER,
) -> ComposedSettings | None:
    """live の configFile に settingsSync の全層を順に重ねた結果を返す。宣言が無ければ None。

    configFile が無ければ template（計算 overlay 込み）を seed する段が先頭に入る。
    seed したテキストは template と等しいので SSOT 層は重ねず、overlay 層だけが続く。
    後段は前段の結果テキストを読むため、先の変更を捨てる事故が起きない。
    """
    resolved = _resolve_template(cfg, repo)
    if resolved is None:
        return None
    settings_format = resolved.settings_format
    live_path = live_dir / resolved.config_file
    seeded = not reader.is_file(live_path)
    steps: list[SettingsStep] = []
    if seeded:
        text = _seeded_template_text(cfg, resolved)
        steps.append(SettingsStep(
            kind="settings-template",
            source_rel=resolved.source_rel,
            text=text,
            change=SettingsChange("", ()),
        ))
    else:
        text = reader.read_text(live_path)

    ssot, overlays = _layers(cfg, repo, resolved)
    for layer in (overlays if seeded else (ssot, *overlays)):
        step = _apply_layer(text, settings_format, layer)
        if step is None:
            continue
        text = step.text
        steps.append(step)
    return ComposedSettings(
        config_file=resolved.config_file, seeded=seeded, steps=tuple(steps), text=text,
    )


def _layer_drifts(live: dict, config_file: str, layer: _Layer) -> list[Drift]:
    found = [
        Drift(path=f"{config_file}#{key}", kind="changed")
        for key in _changed_keys(live, layer.expected, layer.keys)
    ]
    found += [
        Drift(path=f"{config_file}#{key}", kind="obsolete")
        for key in layer.removals
        if _get_dotted(live, key) is not None
    ]
    return found


def drifts(
    cfg: dict, repo: Path, live_dir: Path, reader: LiveReader = HOST_READER,
) -> list[Drift]:
    """settingsSync の宣言キーについて live ↔ template（SSOT + overlay）の drift を返す。

    比較は構造化データのパース結果同士で行う（インデント等のフォーマット差は無視）。
    層は compose と同じ _layers から取る。live の読み取りは reader 経由。
    """
    resolved = _resolve_template(cfg, repo)
    if resolved is None:
        return []
    config_file = resolved.config_file
    settings_format = resolved.settings_format
    template = resolved.template
    live_path = live_dir / config_file

    if not reader.is_file(live_path):
        return [Drift(path=config_file, kind="missing")]

    live = _parse_settings_text(reader.read_text(live_path), settings_format)
    ssot, overlays = _layers(cfg, repo, resolved)
    found = _layer_drifts(live, config_file, ssot)

    # checkOnlyKeys: plugin の有効化など live-first で変わるキーの還流漏れ検出。
    # push では書かない（apply は触らない）ため、live にだけ存在するエントリは
    # SSOT テンプレートへの還流忘れとして報告する。テンプレート側にだけある
    # エントリは新マシン用の seed 既定値なので drift にしない（2026-08-09 に
    # cloudflare plugin の還流漏れが検出されないまま放置された対策）。
    for key in cfg.get("settingsSync", {}).get("checkOnlyKeys", []):
        if _overlay_manages_key(key, resolved.extras_overlay_values):
            continue
        live_value = _get_dotted(live, key)
        if live_value is None:
            continue
        template_value = _get_dotted(template, key)
        if isinstance(live_value, dict):
            template_entries = template_value if isinstance(template_value, dict) else {}
            found += [
                Drift(path=f"{config_file}#{key}.{subkey}", kind="unreconciled")
                for subkey in live_value
                if subkey not in template_entries
            ]
        elif live_value != template_value:
            found.append(Drift(path=f"{config_file}#{key}", kind="unreconciled"))

    for layer in overlays:
        found += _layer_drifts(live, config_file, layer)

    found += [
        Drift(path=f"{config_file}#{key}", kind="changed")
        for key, value in resolved.extras_overlay_values.items()
        if _get_dotted(live, key) != value
    ]

    return found
