## 検証ループ（harunon-harness）

編集後は `"$(mise which python3)" scripts/run-tests.py -k <module>` → `scripts/run-tests.py` → `scripts/validate-harness.py` → `scripts/distribute.py <target> --check`。.sh を触ったら `shellcheck -S warning`。

## CI が赤いとき

`gh run view <run-id> --log` で失敗 step を見て、検証ループで再現・修正し、承認を得て push。赤のまま merge しない（merge はユーザー確認待ち）。

Core Workflow の現在地は `python3 <skill-dir>/scripts/harness.py status`（run-change skill）。遷移が決まらない時だけ推測せず聞く（止めるのはその遷移だけ）。
