#!/usr/bin/env python3
"""hook protocol conformance 契約そのものの形を検証する。

実際の runtime 挙動との突き合わせは scripts/tests/node/hook-protocol-conformance.test.ts が
両 bridge を駆動して行う。ここでは契約が「黙って緩む」ことを防ぐ:
divergence に理由が無い / decision が未知 / ケースが消える、を落とす。
"""
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACT = REPO_ROOT / "scripts/tests/fixtures/hook-protocol.json"
NODE_SUITE = REPO_ROOT / "scripts/tests/node/hook-protocol-conformance.test.ts"

DECISIONS = {"allow", "deny", "ask", "rewrite"}


class TestHookProtocolContract(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_contract_is_not_empty(self):
        self.assertGreaterEqual(len(self.contract["cases"]), 5)

    def test_case_ids_are_unique(self):
        ids = [c["id"] for c in self.contract["cases"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_case_declares_description_hook_and_expect(self):
        for case in self.contract["cases"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(case.get("description", "").strip())
                self.assertIn("hook", case)
                self.assertIn(case["expect"]["decision"], DECISIONS)

    def test_divergence_requires_a_reason(self):
        for case in self.contract["cases"]:
            for runtime, spec in (case.get("divergence") or {}).items():
                with self.subTest(case=case["id"], runtime=runtime):
                    self.assertIn(spec["decision"], DECISIONS)
                    self.assertTrue(
                        str(spec.get("reason", "")).strip(),
                        "divergence は理由必須（ホスト能力差かドリフトかを区別するため）",
                    )

    def test_known_host_divergences_are_still_declared(self):
        """既知の runtime 差が宣言から消えたら落ちる。

        黙って揃うのも黙ってズレるのも防ぐ。実挙動が変わったなら node 側の
        conformance が落ちるので、両方を更新する必要がある。
        wire protocol は hookRunner 1 本になったので、残る差は adapter がホストへ
        decision を写す部分だけ: 確認 UI が無い runtime（opencode / omp）は ask を deny に、
        updatedInput を書き戻さない omp は rewrite を allow に落とす。
        opencode の updatedInput 部分反映（command だけ）は 2026-09-03 に揃えたので、
        divergence として復活したらドリフト。
        """
        declared = {
            case["id"]: set((case.get("divergence") or {}).keys())
            for case in self.contract["cases"]
        }
        self.assertEqual(
            declared["decision-ask-requests-confirmation"], {"opencode", "omp", "codex"}
        )
        self.assertEqual(declared["updated-input-rewrites-command"], {"omp"})
        self.assertEqual(declared["updated-input-non-command-fields"], {"omp"})

    def test_node_suite_consumes_the_contract(self):
        body = NODE_SUITE.read_text(encoding="utf-8")
        self.assertIn("scripts/tests/fixtures/hook-protocol.json", body)
        # 4 runtime の adapter を回していること
        self.assertIn("opencode-plugins/claude-hooks-bridge.js", body)
        self.assertIn("pi-extensions/claude-hooks-bridge.ts", body)
        self.assertIn("omp-extensions/omp-denial-reason.js", body)
        self.assertIn("runtimes/codex/harunon-core/scripts/codex_hook.py", body)

    def test_contract_is_not_distributed(self):
        """実行時に読まれない契約を policy/ に置かない（5 runtime への無駄な配布を避ける）。"""
        self.assertFalse((REPO_ROOT / "packages/core/policy/hook-protocol.json").exists())


if __name__ == "__main__":
    unittest.main()
