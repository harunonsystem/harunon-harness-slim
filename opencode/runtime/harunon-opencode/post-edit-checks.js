// post-edit-checks
//
// OpenCode の tool.execute.after で write / edit 直後のファイルに Claude Code の
// PostToolUse 相当の品質チェックを掛け、指摘を tool result 末尾に追記する adapter
// （モデルが自己修正できる。block はしない）。判定本体は ../hook-runner/post-edit.js →
// runtime/claude-hooks/post-edit-checks.sh。ここが持つのは「編集 path の取り出し方
// （output.args.filePath）」と「output.output への追記」だけ。.md の GFM 自動修正は
// fix-gfm-tables.js（file.edited）が既に担うため markdown: false で重ねない。

import { postEditFindings } from "../hook-runner/post-edit.js";

const EDIT_TOOLS = new Set(["edit", "write"]);

export function appendFindings(output, findings) {
  const existing = typeof output.output === "string" ? output.output : "";
  output.output = `${existing}\n\n[post-edit-check]\n${findings}`;
}

export const PostEditChecks = async ({ hooksDir } = {}) => {
  return {
    "tool.execute.after": async (input, output) => {
      if (!EDIT_TOOLS.has(input?.tool)) return;
      const findings = await postEditFindings(output?.args?.filePath, { hooksDir, markdown: false });
      if (!findings) return;
      appendFindings(output, findings);
    },
  };
};
