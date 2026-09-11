#!/usr/bin/env python3
"""危険コマンド判定の純粋な述語を subprocess 越しに直接テストする。

block-dangerous-in-bash.sh / command-normalize.sh の1回限りの実行に依存する
test_block_dangerous_in_bash.py の主 subprocess テストとは別に、両ファイルが
提供する述語関数（normalize_command / ere_matches / command_origin_matches /
_push_is_standalone / _push_targets_protected_ref）を hook の wire protocol
（stdin JSON・table 読み込み・exit code 規約）を経由せず直接呼ぶ。

各アサーションは新しい bash プロセスを1つ起動する（`source` 後の
`set -euo pipefail` が呼び出し側スクリプトに伝播して後続コマンドを
巻き込むのを避けるため。既存の EreMatchesGrepParityTestCase と同じ形）。
"""
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / "packages" / "core" / "hooks"
NORMALIZE_LIB = HOOKS_DIR / "lib" / "command-normalize.sh"
DANGEROUS_HOOK = HOOKS_DIR / "block-dangerous-in-bash.sh"


def _call(sources: list, fn: str, *args: str) -> subprocess.CompletedProcess:
    source_lines = "; ".join(f'source "{p}"' for p in sources)
    script = f'{source_lines}; {fn} "$@"'
    return subprocess.run(
        ["bash", "-c", script, "bash", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _normalize(command: str) -> str:
    result = _call([NORMALIZE_LIB], "normalize_command", command)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _ere_matches(text: str, ere: str, nocase: bool = False) -> bool:
    fn = "ere_matches_nocase" if nocase else "ere_matches"
    result = _call([NORMALIZE_LIB], fn, text, ere)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def _command_origin_matches(command: str, ere: str) -> int:
    result = _call([NORMALIZE_LIB], "command_origin_matches", command, ere)
    return result.returncode


def _push_is_standalone(command: str) -> bool:
    result = _call([NORMALIZE_LIB, DANGEROUS_HOOK], "_push_is_standalone", command)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def _push_targets_protected_ref(command: str) -> bool:
    result = _call([NORMALIZE_LIB, DANGEROUS_HOOK], "_push_targets_protected_ref", command)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


class EreMatchesGrepParityTestCase(unittest.TestCase):
    """lib/command-normalize.sh の ere_matches が grep -qE と同じ行単位の判定をするか。

    hook は1判定あたり25前後の grep パイプラインを bash の =~ に置き換えた（fork 削減）。
    =~ は行の概念が無いため、`^` が2行目に効かない・否定文字クラスが改行を跨ぐという
    差があり、ヘルパ側で行分割して吸収している。ここが崩れると複数行コマンドの判定が
    grep 時代から無言でズレる。
    """

    def test_anchor_matches_at_start_of_any_line(self):
        self.assertTrue(_ere_matches("echo x\ngit rebase main", "^git[[:space:]]+rebase"))

    def test_negated_class_does_not_cross_newline(self):
        # grep は行単位なので `[^;&]*` は改行を跨がない。=~ 素のままだと一致してしまう
        self.assertFalse(_ere_matches("git x\ny push", "git[[:space:]]+[^;&]*push"))
        self.assertTrue(_ere_matches("git x y push", "git[[:space:]]+[^;&]*push"))

    def test_last_line_without_trailing_newline_is_evaluated(self):
        self.assertTrue(_ere_matches("a\nb\ngit push", "^git push$"))

    def test_nocase_variant(self):
        self.assertTrue(_ere_matches("gh api graphql -f query=Mutation{", "mutation", nocase=True))
        self.assertFalse(_ere_matches("gh api graphql -f query=Mutation{", "mutation"))

    def test_no_verify_posix_equivalent_of_word_boundary(self):
        ere = "--no-verify([^A-Za-z0-9_]|$)"
        self.assertTrue(_ere_matches("git push --no-verify", ere))
        self.assertTrue(_ere_matches("git push --no-verify origin", ere))
        self.assertFalse(_ere_matches("git push --no-verifyx", ere))


class NormalizeQuoteHandlingTestCase(unittest.TestCase):
    """normalize_command の quote-aware lexer が中身を実行意味どおりに畳むか。

    検体は分割して組み立てる（このテストを編集するセッション自身の hook が
    検体に反応するのを防ぐ規約）。
    """

    P = "git"
    PUSH = P + " push"
    COMMIT = P + " commit"
    GIT_PUSH_ERE = f"{P}[[:space:]]+push"

    # quote 内は無害（allow が期待される、旧: NormalizeAllowedFalsePositiveTestCase）
    ALLOWED_CASES = [
        f'echo "a; {PUSH}"',
        f"echo 'a; {PUSH}'",
        f'echo "x && {PUSH}"',
        f'printf "%s" "run | {PUSH} later"',
        f'echo "run; {COMMIT}" > note.txt',
        f'{COMMIT} -m "docs: mention {PUSH} policy"',
        f"{COMMIT} -m 'chore: forbid {PUSH}'",
        f"echo hi # {PUSH}",
        f"echo 'bash -c \"{PUSH}\"'",
        f"echo '$({PUSH})'",
        f'echo "it\'s a {P} thing"',
        "echo don't stop",
        f"echo 'see `{PUSH}` docs'",
    ]

    # quote/escape 越しでも実行位置に来る = deny が期待される（旧: NormalizeTruePositiveTestCase）
    BLOCKED_CASES = [
        f"bash -c '{PUSH}'",
        f'bash -c "{PUSH}"',
        f"bash -c $'{PUSH}'",
        f'''sh -c "sh -c '{PUSH}'"''',
        f"eval '{PUSH} origin main'",
        f"({PUSH})",
        f"if true; then {PUSH}; fi",
        f'{P} "push" origin feature',
        f"\\{P} push origin feature",
        f"''{P} push origin feature",
        "g'i't push origin feature",
        f'echo "result: `{PUSH} origin main`"',
        f"`{PUSH} origin main`",
    ]

    def test_quote_neutral_cases_do_not_normalize_to_a_push_match(self):
        for command in self.ALLOWED_CASES:
            with self.subTest(command=command):
                normalized = _normalize(command)
                self.assertFalse(
                    _ere_matches(normalized, self.GIT_PUSH_ERE),
                    msg=f"normalized={normalized!r}",
                )

    def test_evasion_attempts_still_normalize_to_a_push_match(self):
        for command in self.BLOCKED_CASES:
            with self.subTest(command=command):
                normalized = _normalize(command)
                self.assertTrue(
                    _ere_matches(normalized, self.GIT_PUSH_ERE),
                    msg=f"normalized={normalized!r}",
                )

    def test_git_clean_dash_fd_with_empty_double_quotes_is_word_end_matched(self):
        # neutralize の中和文字が `~`（wordEndEre 適合）であることの根拠ケース。
        normalized = _normalize(f'{self.P} clean -fd""')
        self.assertTrue(_ere_matches(normalized, "clean[[:space:]]+-fd([^A-Za-z0-9_/-]|$)"))


class GitGlobalOptionStrippingTestCase(unittest.TestCase):
    """P0-A: git のグローバルオプションを generic に落として subcommand を隣接させる。

    旧実装は固定 allowlist しか剥がせず、未知のオプションを挟むだけで push gate が
    丸ごと未発火した（実測 ALLOW）。command_origin_matches は origin 直後に対象語が
    現れるかを見るため、ここが壊れると判定そのものが不発になる。
    """

    P = "git"
    PUSH_ERE = "git[[:space:]]+push"

    def test_no_pager_option_is_stripped(self):
        self.assertEqual(_command_origin_matches(f"{self.P} --no-pager push origin feature", self.PUSH_ERE), 0)

    def test_dash_capital_p_option_is_stripped(self):
        self.assertEqual(_command_origin_matches(f"{self.P} -P push origin feature", self.PUSH_ERE), 0)

    def test_git_dir_space_form_is_stripped(self):
        self.assertEqual(
            _command_origin_matches(f"{self.P} --git-dir /tmp/x push origin feature", self.PUSH_ERE), 0
        )

    def test_literal_pathspecs_option_is_stripped(self):
        self.assertEqual(
            _command_origin_matches(f"{self.P} --literal-pathspecs push origin feature", self.PUSH_ERE), 0
        )

    def test_exec_path_space_form_is_stripped(self):
        self.assertEqual(
            _command_origin_matches(f"{self.P} --exec-path /tmp/x push origin feature", self.PUSH_ERE), 0
        )

    def test_dash_capital_c_equals_form_is_stripped(self):
        self.assertEqual(_command_origin_matches(f"{self.P} -C=/tmp/x push origin feature", self.PUSH_ERE), 0)


class PushIsStandaloneTestCase(unittest.TestCase):
    """_push_is_standalone: push 承認が効くのは単独・1回の push だけ。"""

    def test_single_push_is_standalone(self):
        self.assertTrue(_push_is_standalone("git push origin main"))

    def test_chained_with_and_and_is_not_standalone(self):
        self.assertFalse(_push_is_standalone("git switch other && git push"))

    def test_chained_with_semicolon_is_not_standalone(self):
        self.assertFalse(_push_is_standalone("git push; echo done"))

    def test_chained_with_or_or_is_not_standalone(self):
        self.assertFalse(_push_is_standalone("git push || echo failed"))

    def test_newline_separated_is_not_standalone(self):
        self.assertFalse(_push_is_standalone("git push\ngit push"))

    def test_pipe_to_readonly_sink_is_standalone(self):
        for sink in ("tee log", "cat", "grep foo", "wc -l", "jq .", "rtk log"):
            with self.subTest(sink=sink):
                self.assertTrue(_push_is_standalone(f"git push 2>&1 | {sink}"))

    def test_pipe_to_non_sink_command_is_not_standalone(self):
        self.assertFalse(_push_is_standalone("git push | rm -rf /tmp/x"))


class PushTargetsProtectedRefTestCase(unittest.TestCase):
    """_push_targets_protected_ref: 保護 ref（main/master）・force・+refspec を検出する。

    --force-with-lease は feature branch 相手なら許容される（rules/git-safety.md）。
    この carve-out は「force フラグの語彙に --force-with-lease を含めない」実装で
    成立しているので、fwl + main の組み合わせは dst 判定側で捕まる。
    """

    def test_plain_push_to_feature_branch_is_not_protected(self):
        self.assertFalse(_push_targets_protected_ref("git push origin feature"))

    def test_push_to_main_is_protected(self):
        self.assertTrue(_push_targets_protected_ref("git push origin main"))

    def test_push_to_master_is_protected(self):
        self.assertTrue(_push_targets_protected_ref("git push origin master"))

    def test_push_to_refs_heads_main_is_protected(self):
        self.assertTrue(_push_targets_protected_ref("git push origin refs/heads/main"))

    def test_bare_push_to_main_is_protected(self):
        self.assertTrue(_push_targets_protected_ref("git push main"))

    def test_force_flag_is_protected_regardless_of_target(self):
        self.assertTrue(_push_targets_protected_ref("git push --force origin feature"))

    def test_short_combined_force_flag_is_protected(self):
        self.assertTrue(_push_targets_protected_ref("git push -f origin feature"))

    def test_force_with_lease_to_feature_branch_is_not_protected(self):
        self.assertFalse(_push_targets_protected_ref("git push --force-with-lease origin feature"))

    def test_force_with_lease_to_main_is_protected(self):
        self.assertTrue(_push_targets_protected_ref("git push --force-with-lease origin main"))

    def test_plus_refspec_is_protected_regardless_of_target(self):
        self.assertTrue(_push_targets_protected_ref("git push origin +HEAD:refs/heads/feature"))

    def test_push_option_with_value_is_not_mistaken_for_target(self):
        self.assertFalse(
            _push_targets_protected_ref("git push --push-option=notify origin feature")
        )

    def test_rtk_git_push_prefix_is_recognized(self):
        self.assertTrue(_push_targets_protected_ref("rtk git push origin main"))


if __name__ == "__main__":
    unittest.main()
