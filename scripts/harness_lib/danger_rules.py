"""harness_lib.danger_rules — 危険コマンドルール SSOT table の schema・整合性検証。

packages/core/policy/danger-rules.json は危険コマンドルールの読み取り専用 SSOT
台帳。運用時点での関わり方は3種類:
  - 生成: opencode/omp の permission map（distribute 時に permission_globs() で
    checked-in ファイルへ合成。settings_sync.py 参照）
  - runtime 読み込み: block-dangerous-in-bash.sh（hook）と
    packages/core/pi-extensions/confirm-destructive.ts（pi extension）が
    table を実行時に直接読む。どちらも table のコピーを保持しないため
    validator の照合対象外（読めば必然的に一致する）
  - 照合が必要な独立表現: claude settings.json の deny（forward 照合）、
    settings.json の autoMode（hard_deny/soft_deny プロジェクション照合）、
    AGENTS.md の散文（token 照合）
ここでは「table が独立表現と矛盾していないか」だけを検証する。sources 側の
意味は一切変更しない。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import hook_pipeline
from .jsonio import JsonLoadError, load_json_object
from .policy_kernel import TableSpec, check_table
from .schema import validate as validate_schema
from .validator_registry import Finding

_TABLE_PATH = "packages/core/policy/danger-rules.json"
_EXTRA_TABLE_PATH = "packages/extras/_active/policy/danger-rules.extra.json"
_SCHEMA_PATH = "schemas/danger-rules.schema.json"
_EXTRA_SCHEMA_PATH = "schemas/danger-rules.extra.schema.json"
_OPENCODE_OVERLAY_PATH = "packages/targets/opencode/permission-overlay.json"
_OMP_CONFIG_PATH = "packages/targets/omp/config.yml"
_CLAUDE_SETTINGS_PATH = "packages/core/settings.json"
_CLAUDE_TARGET_CONFIG_PATH = "packages/targets/claude/config.json"
_HOOK_FILE_PATH = "packages/core/hooks/block-dangerous-in-bash.sh"
_BLOCK_DANGEROUS_HOOK_ID = "block-dangerous-in-bash"

# block-dangerous-in-bash.sh を経由する runtime（hook-pipeline.json の
# block-dangerous-in-bash.runtimes と独立に、「hook という経路の対象になり
# うる runtime 集合」を宣言する）。omp は 2026-08-30 から
# extensions/omp-denial-reason.js が同じ hook を HARNESS_RUNTIME=omp で呼ぶ
# （deny 主体は bash.patterns のまま。hook は理由の説明と第二防衛線）。
_HOOK_CAPABLE_RUNTIMES = {"claude", "pi", "opencode", "codex", "omp"}

# hook 側の custom_<slug>() 定義を検出する（既存の関数定義スタイル: 行頭 +
# `custom_` + kebab->snake の id + `() {`）。
_CUSTOM_FN_RE = re.compile(r"^custom_([A-Za-z0-9_]+)\(\)\s*\{", re.MULTILINE)


def _schema_errors(data: object, schema_rel_path: str, prefix: str, repo_root: Path) -> list[str]:
    """schema ファイルで data を検証し、prefix を付けたエラーを返す。"""
    schema_path = repo_root / schema_rel_path
    if not schema_path.is_file():
        raise FileNotFoundError(f"schema file not found: {schema_path}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return [f"{prefix}: {e}" for e in validate_schema(data, schema)]


def _validate_schema(table: dict, repo_root: Path) -> list[str]:
    """table 全体を検証する。

    構造契約（id の kebab-case・action/impl の語彙・targets の部分集合性・
    absent/overrides/match/prose/notes/autoMode の形）は
    schemas/danger-rules.schema.json（JSON Schema）が担う。ここでは schema
    単体では表現できない cross-field 制約だけを追加検証する: rule id の重複、
    absent.<target> と targets の重複、autoMode.tier と action の整合性。
    """
    errors = _schema_errors(table, _SCHEMA_PATH, "schema", repo_root)
    errors.extend(_posix_ere_constant_errors(table))

    rules = table.get("rules")
    if not isinstance(rules, list):
        return errors

    seen_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        errors.extend(_rule_cross_field_errors(rule))
        rule_id = rule.get("id")
        if isinstance(rule_id, str):
            if rule_id in seen_ids:
                errors.append(f"schema: rule id が重複しています: {rule_id}")
            seen_ids.add(rule_id)

    return errors


def _rule_cross_field_errors(rule: dict) -> list[str]:
    """1 rule 内の、schema 単体では表現できないフィールド間の整合性だけを検証する。

    autoMode は claude 専用チャネル（settings.json の hard_deny/soft_deny 配列）
    なので、宣言する rule は targets に claude を持つ必要がある。hard_deny は
    無条件ブロックなので action が block（実効的に確実に block される）rule
    のみ許す。soft_deny はユーザー許可があれば通す runtime 側の block/confirm
    に対応する。
    """
    errors: list[str] = []
    rule_id = rule.get("id", "<unknown>")
    targets = rule.get("targets")
    targets = targets if isinstance(targets, list) else []

    absent = rule.get("absent")
    if isinstance(absent, dict):
        for target in absent:
            if target in targets:
                errors.append(f"schema[{rule_id}]: absent.{target} は targets と重複しています")

    auto_mode = rule.get("autoMode")
    if isinstance(auto_mode, list) and auto_mode:
        if "claude" not in targets:
            errors.append(f"schema[{rule_id}]: autoMode を持つには targets に claude が必要です")
        action = rule.get("action")
        for entry in auto_mode:
            if not isinstance(entry, dict):
                continue
            tier = entry.get("tier")
            if tier == "hard_deny" and action != "block":
                errors.append(f"schema[{rule_id}]: autoMode.hard_deny は action が block の rule にのみ許されます")
            if tier == "soft_deny" and action not in {"block", "confirm"}:
                errors.append(f"schema[{rule_id}]: autoMode.soft_deny は action が block/confirm の rule にのみ許されます")

    errors.extend(_posix_ere_errors(rule))
    return errors


# hook（block-dangerous-in-bash.sh）は match.ere を bash の `=~`（libc の POSIX ERE）で
# 判定する。grep -E の GNU 拡張（\b \w \s \d \< \>）は macOS の libc では黙って不一致に
# なり、その rule だけ無言で fail-open するため、table 側で禁止する。
# 後方参照 \1〜\9 も含める: grep -E は受け付けるが bash =~（POSIX ERE）では未定義で、
# macOS では `(a)\1` が `aa` に一致しない（codex review PERF-HOOK-ERE-001）。
# エスケープは先頭から 2 文字ずつ消費して判定する（`\\1` はリテラルの `\` + `1` であって
# 後方参照ではない。search で `\1` を探すと 2 つ目のバックスラッシュから一致して誤検知する）。
_ERE_ESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)
_NON_POSIX_ESCAPED_CHARS = frozenset("bBwWsSdD<>123456789")
_BASH_ERE_CONSTANT_KEYS = ("originEre", "chainOnlyOriginEre", "wordEndEre")


def _non_posix_ere_error(label: str, ere: object) -> str | None:
    if not isinstance(ere, str):
        return None
    for escape in _ERE_ESCAPE_RE.finditer(ere):
        if escape.group(1) in _NON_POSIX_ESCAPED_CHARS:
            return (
                f"{label} に POSIX ERE に無い構文 {escape.group(0)} があります"
                "（hook は bash の =~ で判定するため GNU 拡張・後方参照は使えません。([^A-Za-z0-9_]|$) 等で書く）"
            )
    return None


def _posix_ere_errors(rule: dict) -> list[str]:
    match = rule.get("match")
    ere = match.get("ere") if isinstance(match, dict) else None
    error = _non_posix_ere_error(f"schema[{rule.get('id', '<unknown>')}]: match.ere", ere)
    return [error] if error else []


def _posix_ere_constant_errors(table: dict) -> list[str]:
    constants = table.get("constants")
    if not isinstance(constants, dict):
        return []
    errors = []
    for key in _BASH_ERE_CONSTANT_KEYS:
        error = _non_posix_ere_error(f"schema: constants.{key}", constants.get(key))
        if error:
            errors.append(error)
    return errors


def _validate_extra_table(extra: dict, core_ids: set[str], repo_root: Path) -> list[str]:
    """extras table（会社・プロジェクト固有の追加ルール）の schema を検証する。

    extras table の消費者は block-dangerous-in-bash.sh（claude）だけなので、
    そこで成立しない表現をエラーにする: custom impl（実装関数が hook 側にしか
    無い）、match.globs（opencode/omp の permission map 生成は core table のみが
    対象で、書いても無言の no-op になる）、ere なし・targets に claude なし
    （どのランタイムにも効かない死にルール）。
    """
    # 手書き JSON なのでトップレベル・rule とも dict 以外があり得る。ここで
    # 型を確認しないと .get で AttributeError になり、validator が診断を返さず
    # traceback で終了する（codex review P2）。
    if not isinstance(extra, dict):
        return ["extra-schema: table はオブジェクトである必要があります"]

    # 構造契約（version の型・rule の id/action/impl/targets/match 等の形）は
    # schemas/danger-rules.extra.schema.json が担う。ここでは schema 単体では
    # 表現できない意味的制約だけを追加検証する: id の core/extras 間重複、
    # custom impl 禁止、match.globs 禁止、match.ere 必須、targets に claude 必須
    # （すべて extras table の消費者が claude の hook 一本であることに由来する）。
    errors = _schema_errors(extra, _EXTRA_SCHEMA_PATH, "extra-schema", repo_root)
    rules = extra.get("rules")
    if not isinstance(rules, list):
        errors.append("extra-schema: rules はリストである必要があります")
        return errors

    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            errors.append("extra-schema: rule はオブジェクトである必要があります")
            continue
        rule_id = rule.get("id", "<unknown>")
        if rule_id in seen or rule_id in core_ids:
            errors.append(f"extra-schema: rule id が core / extras 間で重複しています: {rule_id}")
        seen.add(rule_id)
        if rule.get("impl") == "custom":
            errors.append(f"extra-schema[{rule_id}]: custom impl は extras table に置けません（実装関数は hook 側にしか無い）")
        if rule.get("match", {}).get("globs"):
            errors.append(f"extra-schema[{rule_id}]: match.globs は extras table では生成対象外です（core table にのみ書く）")
        if not rule.get("match", {}).get("ere"):
            errors.append(f"extra-schema[{rule_id}]: match.ere が必要です（hook は ere でしか判定しない）")
        errors.extend(e.replace("schema[", "extra-schema[", 1) for e in _posix_ere_errors(rule))
        if "claude" not in rule.get("targets", []):
            errors.append(f"extra-schema[{rule_id}]: targets に claude が必要です（extras table の消費者は claude の hook のみ）")
    return errors


def _effective_action(rule: dict, target: str) -> str:
    override = rule.get("overrides", {}).get(target)
    return override["action"] if override else rule["action"]


def _expected_list_name(target: str, action: str) -> str | None:
    """target/action から要求される permission tier を返す。該当なければ None。

    tier の語彙は target ごとに異なる: omp の実チャネル（bash.patterns）は
    approval: deny|prompt（2026-08 実測: omp は permissions キーを読まず、
    config get permissions は Unknown setting を返す）。claude/opencode は
    従来どおり deny/ask。
    """
    if action == "warn":
        return None
    if target == "omp":
        if action == "block":
            return "deny"
        if action == "confirm":
            return "prompt"
        return None
    if action == "block":
        return "deny"
    if action == "confirm":
        # claude settings.json には ask 層が無いため、confirm は deny で表現する
        return "deny" if target == "claude" else "ask"
    return None


def _omp_glob_variants(glob: str) -> tuple[str, ...]:
    """omp の full-command glob に ERE が受け付ける省略 variant を加える。

    danger-rules.json の glob は各 rule の代表形を保ち、omp だけが必要とする
    rtk prefix・bare command・npm の長形式を projection 側で決定的に展開する。
    環境変数 prefix は omp の full-string glob では表現できないため、ここでは
    matcher の意味を変更せず、既存の rule notes で未対応として扱う。
    """
    variants: list[str] = [glob]

    def add(value: str) -> None:
        if value not in variants:
            variants.append(value)

    if glob.startswith("git "):
        add("rtk " + glob)

    if glob.startswith("git ") and glob.endswith(" *"):
        bare = glob[:-2]
        add(bare)
        if bare.startswith("git "):
            add("rtk " + bare)

    if glob.startswith("npm ") and " -g " in glob:
        add(glob.replace(" -g ", " --global ", 1))

    return tuple(variants)


def permission_globs(table: dict, target: str) -> dict[str, str]:
    """table の rules から target 向けの glob -> tier マップを計算する。

    opencode/omp の permission map はこの関数の出力を distribute 時に生成・合成する
    （settings_sync.py 参照）。tier は target に応じて deny/ask/prompt になる。
    claude は settingsSync 非対象のため呼び出し元では使わない。
    """
    result: dict[str, str] = {}
    for rule in table["rules"]:
        targets = rule["targets"]
        if target not in targets:
            continue
        globs = rule.get("match", {}).get("globs", {}).get(target)
        if not globs:
            continue
        tier = _expected_list_name(target, _effective_action(rule, target))
        if tier is None:
            continue
        for glob in globs:
            projected = _omp_glob_variants(glob) if target == "omp" else (glob,)
            for variant in projected:
                result[variant] = tier
    return result


def auto_mode_rules(table: dict) -> dict[str, list[str]]:
    """table の rule.autoMode から claude settings.json の autoMode 投影値を計算する。

    出力は {"hard_deny": ["$defaults", ...], "soft_deny": ["$defaults", ...]}。
    "$defaults" を各 tier の先頭に固定するのは、settings.json の autoMode 契約
    （$defaults を欠くと組み込みルールが丸ごと置き換わる）を守るため。prose の
    並びは rule 配列の出現順（同一 tier 内で複数 rule から来る場合も安定）。
    """
    result: dict[str, list[str]] = {"hard_deny": ["$defaults"], "soft_deny": ["$defaults"]}
    for rule in table.get("rules", []):
        for entry in rule.get("autoMode", []) or []:
            tier = entry.get("tier")
            prose = entry.get("prose")
            if tier in result and prose:
                result[tier].append(prose)
    return result


def _check_auto_mode_projection(table: dict, repo_root: Path) -> list[str]:
    """claude settings.json の autoMode が danger-rules.json から導出した値と一致するか検証する。

    settings.json は autoMode の投影先（生成物）であり、danger-rules.json の
    rule.autoMode が SSOT。ずれている場合は sync-auto-mode-rules.py の実行を促す。
    """
    settings_path = repo_root / _CLAUDE_SETTINGS_PATH
    if not settings_path.is_file():
        return []
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    expected = auto_mode_rules(table)
    actual = settings.get("autoMode", {})
    errors: list[str] = []
    for tier, expected_list in expected.items():
        if actual.get(tier) != expected_list:
            errors.append(
                f"auto-mode[{tier}]: settings.json の autoMode.{tier} が danger-rules.json と"
                " 一致しません。scripts/sync-auto-mode-rules.py を実行してください"
            )
    return errors


def _check_auto_mode_sync_keys(repo_root: Path) -> list[str]:
    """claude target config.json の settingsSync.keys が autoMode の 2 tier を対で宣言しているか検証する。

    autoMode の投影値そのもの（danger-rules.json ⇔ settings.json）は
    _check_auto_mode_projection が照合するが、それが settingsSync 経由で live に
    届くかどうかは settingsSync.keys の宣言に懸かっている。片方の tier だけ
    keys にあると当該 tier が --check / --push の対象外になり、live に古い
    classifier rule が残ったまま気づけない。ここでは settings.json への投影が
    live に届く経路（settingsSync）まで含めて autoMode の SSOT 契約を守るための
    check を行う。
    """
    config_path = repo_root / _CLAUDE_TARGET_CONFIG_PATH
    if not config_path.is_file():
        return []
    config = json.loads(config_path.read_text(encoding="utf-8"))
    keys = config.get("settingsSync", {}).get("keys", []) or []

    errors: list[str] = []
    required = ("autoMode.hard_deny", "autoMode.soft_deny")
    missing = [key for key in required if key not in keys]
    if missing:
        errors.append(
            "auto-mode[sync-keys]: claude settingsSync.keys は autoMode.hard_deny と"
            " autoMode.soft_deny を対で宣言する必要があります"
            f"（欠落: {', '.join(missing)}）。片方だけだと当該 tier が --check / --push の"
            " 対象外になり live に古い classifier rule が残る"
        )
    if "autoMode" in keys:
        errors.append(
            "auto-mode[sync-keys]: claude settingsSync.keys の autoMode（丸ごと）は廃止。"
            "autoMode.hard_deny / autoMode.soft_deny の対に置き換える"
            "（autoMode.environment は live 専用）"
        )
    return errors


def _check_glob_surface(
    target: str,
    computed: dict[str, str],
    present: set[str],
    *,
    relation: str,
) -> list[str]:
    """target 向けの expected surface（computed = permission_globs 出力）と checked-in
    ファイルの実際の glob 集合（present）を relation で比較する。

    relation はどちらが SSOT かで向きが変わる:
      - "disjoint": distribute が生成する側（opencode/omp）。checked-in に
        computed glob が残っていてはならない（再混入検出）。
      - "subset": checked-in が SSOT 側（claude は settingsSync 非対象）。
        computed glob（deny のみ）が checked-in に既に現存していなければならない。
    """
    if relation == "disjoint":
        return [
            f"reintroduced[{target}]: {glob!r} は distribute 生成対象のはずですが "
            "checked-in ファイルに残っています"
            for glob in sorted(set(computed) & present)
        ]
    return [
        f"forward[{target}]: {glob!r} が {target}.deny に見つかりません"
        for glob, tier in sorted(computed.items())
        if tier == "deny" and glob not in present
    ]


def _check_claude_forward_globs(rules: list[dict], claude_deny: set[str]) -> list[str]:
    """claude 向け match.globs.claude が settings.json の deny に現存するか検証する。

    opencode/omp は permission map を distribute 時に生成するため、この forward
    照合は claude のみを対象にする（生成後はトートロジーになるため対象外）。
    """
    computed = permission_globs({"rules": rules}, "claude")
    return _check_glob_surface("claude", computed, claude_deny, relation="subset")


def _check_no_reintroduced_globs(table: dict, repo_root: Path) -> list[str]:
    """opencode/omp の checked-in permission map に table 由来 glob が再混入していないか検証する。

    table 由来の deny/ask エントリは distribute 時に permission_globs() で生成されるため、
    checked-in ファイル（permission-overlay.json / config.yml）には存在してはならない。
    """
    errors: list[str] = []
    # omp の照合は PyYAML に依存する。settings_sync と同じく yaml は optional
    # dependency（CI は pip install pyyaml 済みでそちらが正）なので、未インストール
    # 環境では omp 分だけスキップして opencode（JSON）の照合は継続する。
    parsers: list = [("opencode", _parse_opencode_bash)]
    try:
        import yaml  # noqa: F401

        parsers.append(("omp", _parse_omp_bash))
    except ImportError:
        pass
    for target, parser_fn in parsers:
        computed = permission_globs(table, target)
        if not computed:
            continue
        deny, ask = parser_fn(repo_root)
        errors.extend(_check_glob_surface(target, computed, deny | ask, relation="disjoint"))
    return errors


def _check_prose(rules: list[dict], repo_root: Path) -> list[str]:
    """prose エントリの token が対象ファイルに現存するか検証する。"""
    errors: list[str] = []
    cache: dict[str, str] = {}
    for rule in rules:
        for prose in rule.get("prose", []):
            file_rel = prose.get("file")
            token = prose.get("token")
            if not file_rel or not token:
                continue
            if file_rel not in cache:
                path = repo_root / file_rel
                cache[file_rel] = path.read_text(encoding="utf-8") if path.is_file() else ""
            if token not in cache[file_rel]:
                errors.append(f"prose[{rule['id']}]: token {token!r} が {file_rel} に見つかりません")
    return errors


def _parse_opencode_bash(repo_root: Path) -> tuple[set[str], set[str]]:
    path = repo_root / _OPENCODE_OVERLAY_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    bash = data.get("permission", {}).get("bash", {})
    deny = {k for k, v in bash.items() if v == "deny"}
    ask = {k for k, v in bash.items() if v == "ask" and k != "*"}
    return deny, ask


def _parse_omp_bash(repo_root: Path) -> tuple[set[str], set[str]]:
    """omp の実チャネル bash.patterns（{match, approval} の順序付き配列）を読む。

    permissions キーは omp が読まない（2026-08 実測。config get permissions は
    Unknown setting）ため、checked-in table との再混入照合は bash.patterns を見る。
    """
    import yaml

    path = repo_root / _OMP_CONFIG_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    patterns = data.get("bash", {}).get("patterns", []) or []
    deny = {p["match"] for p in patterns if isinstance(p, dict) and p.get("approval") == "deny"}
    prompt = {p["match"] for p in patterns if isinstance(p, dict) and p.get("approval") == "prompt"}
    return deny, prompt


def _parse_claude_deny(repo_root: Path) -> set[str]:
    path = repo_root / _CLAUDE_SETTINGS_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("permissions", {}).get("deny", []))


def _hook_custom_function_slugs(hook_text: str) -> set[str]:
    """hook 内で定義されている custom_<slug>() の slug（id の "-" を "_" にした形）集合を返す。"""
    return {m.group(1) for m in _CUSTOM_FN_RE.finditer(hook_text)}


def _block_dangerous_hook_runtimes(repo_root: Path) -> set[str]:
    """hook-pipeline.json の block-dangerous-in-bash.runtimes を返す。"""
    table = hook_pipeline.load(repo_root)
    for hook in table.get("hooks", []):
        if hook.get("id") == _BLOCK_DANGEROUS_HOOK_ID:
            return set(hook.get("runtimes", []))
    return set()


def _has_hook_channel(rule: dict, target: str, hook_runtimes: set[str], custom_slugs: set[str]) -> bool:
    """target が hook（block-dangerous-in-bash.sh）経由で enforcement されるか判定する。"""
    if target not in _HOOK_CAPABLE_RUNTIMES or target not in hook_runtimes:
        return False
    if rule.get("impl") == "custom":
        if rule.get("id", "").replace("-", "_") not in custom_slugs:
            return False
    else:
        if rule.get("match", {}).get("ere") is None:
            return False
    # hook は対話確認できないため、実効 action が confirm の runtime は
    # hook 経路が無いものとして扱う（ask/prompt は native 層の責務）。
    return _effective_action(rule, target) != "confirm"


def _has_enforcement_channel(rule: dict, target: str, hook_runtimes: set[str], custom_slugs: set[str]) -> bool:
    """rule が target 向けに、いずれかの enforcement channel を持つか判定する。

    channel: hook（claude/pi/opencode/codex 共通）、claude native glob
    （match.globs.claude）、opencode overlay glob（match.globs.opencode）、
    omp bash.patterns（match.globs.omp）、pi extension（match.js）。

    glob 系 channel は glob が宣言されているだけでは不十分: permission_globs()
    は _expected_list_name(target, 実効 action) が None（action が warn 等で
    tier に投影されない）だと当該 rule をスキップし glob を生成しない。宣言だけ
    あって実際には投影されない「見せかけの経路」を経路ありと誤判定しないよう、
    実効 tier が存在する場合のみ channel ありとする。
    """
    if _has_hook_channel(rule, target, hook_runtimes, custom_slugs):
        return True
    globs = rule.get("match", {}).get("globs", {})
    if (
        target in ("claude", "opencode", "omp")
        and globs.get(target)
        and _expected_list_name(target, _effective_action(rule, target)) is not None
    ):
        return True
    if target == "pi" and rule.get("match", {}).get("js"):
        return True
    return False


def _check_enforcement_channels(rules: list[dict], repo_root: Path) -> list[str]:
    """rule の targets に宣言された各 runtime に enforcement channel が実在するか検証する。

    #100 の再発防止: git-no-verify が targets に omp を持ちながら経路がゼロ
    だった穴を機械検出する。逆方向（hook 内の custom_*() のうち、どの rule id
    にも対応しないもの = orphan）も同時に検出する。
    """
    errors: list[str] = []
    hook_runtimes = _block_dangerous_hook_runtimes(repo_root)
    hook_text = (repo_root / _HOOK_FILE_PATH).read_text(encoding="utf-8")
    custom_slugs = _hook_custom_function_slugs(hook_text)

    used_slugs: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("id", "<unknown>")
        if rule.get("impl") == "custom" and isinstance(rule.get("id"), str):
            used_slugs.add(rule["id"].replace("-", "_"))
        for target in rule.get("targets", []) or []:
            if not _has_enforcement_channel(rule, target, hook_runtimes, custom_slugs):
                errors.append(
                    f"enforcement[{rule_id}]: target {target!r} に enforcement channel がありません"
                )

    for slug in sorted(custom_slugs - used_slugs):
        errors.append(
            f"enforcement-orphan: hook の custom_{slug}() がどの rule id にも対応しません"
        )
    return errors


# -- Policy Kernel 適合: TableSpec へ委譲するための薄いアダプタ ---------


def _check_claude_forward_table(table: dict, repo_root: Path) -> list[str]:
    return _check_claude_forward_globs(table.get("rules", []), _parse_claude_deny(repo_root))


def _check_prose_table(table: dict, repo_root: Path) -> list[str]:
    return _check_prose(table.get("rules", []), repo_root)


def _load_extra_table(repo_root: Path) -> dict | None:
    """extras table を読む。無ければ None、壊れていれば JsonLoadError。"""
    extra_path = repo_root / _EXTRA_TABLE_PATH
    if not extra_path.is_file():
        return None
    return load_json_object(extra_path)


def _check_extra_table_policy(table: dict, repo_root: Path) -> list[str]:
    try:
        extra = _load_extra_table(repo_root)
    except JsonLoadError as error:
        return [f"extra-schema: {error.reason}"]
    if extra is None:
        return []
    core_ids = {r["id"] for r in table.get("rules", []) if isinstance(r, dict) and r.get("id")}
    return _validate_extra_table(extra, core_ids, repo_root)


def _check_enforcement_channels_table(table: dict, repo_root: Path) -> list[str]:
    """core + extras の rule を合わせて enforcement channel 検証する（extras は claude hook のみが消費者）。"""
    rules = core_and_extra_rules(table, repo_root)
    return _check_enforcement_channels(rules, repo_root)


def core_and_extra_rules(table: dict, repo_root: Path) -> list[dict]:
    """core table の rules に、存在すれば extras table の rules を連結して返す。"""
    rules = [r for r in table.get("rules", []) if isinstance(r, dict)]
    try:
        extra = _load_extra_table(repo_root)
    except JsonLoadError:
        # 壊れた extras table は _check_extra_table_policy が Finding として報告する
        extra = None
    if extra is not None and isinstance(extra.get("rules"), list):
        rules += [r for r in extra["rules"] if isinstance(r, dict)]
    return rules


def _check_auto_mode_projection_table(table: dict, repo_root: Path) -> list[str]:
    """core + extras の rule.autoMode を合わせて claude settings.json との projection 照合をする。"""
    rules = core_and_extra_rules(table, repo_root)
    errors = _check_auto_mode_projection({"rules": rules}, repo_root)
    errors.extend(_check_auto_mode_sync_keys(repo_root))
    return errors


_DANGER_SPEC = TableSpec(
    name="danger-rules",
    table_rel=_TABLE_PATH,
    validate=_validate_schema,
    checks=[
        _check_claude_forward_table,
        _check_no_reintroduced_globs,
        _check_prose_table,
        _check_extra_table_policy,
        _check_enforcement_channels_table,
        _check_auto_mode_projection_table,
    ],
)


def check(repo_root: Path) -> list[Finding]:
    """danger-rules.json を7つの source と照合し、違反を Finding で返す（空 = OK）。

    table 自体が存在しない場合は何もチェックしない（導入前の repo との後方互換）。
    Policy Kernel (TableSpec + check_table) へ委譲する thin wrapper。
    """
    return check_table(repo_root, _DANGER_SPEC)
