// fix-gfm-tables
//
// OpenCode の file.edited event で Markdown ファイルのテーブルを GFM 形式に自動修正する。
// Claude Code の hooks/fix_gfm_tables.py と同等。

function isTableRow(line) {
  const stripped = line.trim();
  if (!stripped) return false;
  return stripped.includes("|") && !stripped.startsWith("|");
}

function isSeparatorRow(line) {
  const stripped = line.trim();
  return /^[\|\s\-:]+$/.test(stripped) && stripped.includes("-");
}

function fixTableRow(line) {
  const stripped = line.trim();
  if (stripped.startsWith("|") && stripped.endsWith("|")) {
    return line;
  }
  let cells = stripped.split("|").map((c) => c.trim());
  while (cells.length > 0 && cells[0] === "") cells.shift();
  while (cells.length > 0 && cells[cells.length - 1] === "") cells.pop();
  if (cells.length === 0) return line;
  return "| " + cells.join(" | ") + " |";
}

function fenceMarker(line) {
  const stripped = line.trim();
  if (stripped.startsWith("```")) return "```";
  if (stripped.startsWith("~~~")) return "~~~";
  return null;
}

function fixGfmTables(content) {
  const lines = content.split("\n");
  const result = [];
  let inTable = false;
  let openFence = null;

  for (const line of lines) {
    const marker = fenceMarker(line);
    if (openFence !== null) {
      if (marker === openFence) openFence = null;
      result.push(line);
      continue;
    }
    if (marker !== null) {
      openFence = marker;
      inTable = false;
      result.push(line);
      continue;
    }

    const stripped = line.trim();
    if (isTableRow(stripped) || (inTable && isSeparatorRow(stripped))) {
      if (!inTable) inTable = true;
      result.push(fixTableRow(line));
    } else if (inTable && stripped.startsWith("|")) {
      result.push(line);
    } else if (inTable && stripped === "") {
      inTable = false;
      result.push(line);
    } else {
      inTable = false;
      result.push(line);
    }
  }
  return result.join("\n");
}

export const FixGfmTables = async ({ $ }) => {
  return {
    "file.edited": async (input, output) => {
      const filePath = output?.args?.filePath;
      if (!filePath || !filePath.endsWith(".md")) return;

      try {
        const file = Bun.file(filePath);
        const content = await file.text();
        const fixed = fixGfmTables(content);
        if (fixed !== content) {
          await Bun.write(filePath, fixed);
        }
      } catch {
        // ファイルが存在しない場合は無視
      }
    },
  };
};
