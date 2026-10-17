#!/bin/bash
# Keep the hook entry point; the kernel and all runtimes share the policy payload.
# shellcheck source=../../policy/review-router.sh
source "$(dirname "${BASH_SOURCE[0]}")/../../policy/review-router.sh"
