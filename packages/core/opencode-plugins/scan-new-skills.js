// scan-new-skills
//
// OpenCode の tool.execute.after event でスキルインストール後に軽量セキュリティスキャンする。
// Claude Code の hooks/scan-new-skills.sh と同等。

import { readdir } from "node:fs/promises";
import { join } from "node:path";

const SKILLS_DIR = `${process.env.HOME}/.config/opencode/skills`;
const MANIFEST = "/tmp/.opencode-skills-manifest";

async function readManifest() {
  try {
    const { readFile } = await import("node:fs/promises");
    return await readFile(MANIFEST, "utf-8");
  } catch {
    return null;
  }
}

async function writeManifest(content) {
  const { writeFile } = await import("node:fs/promises");
  await writeFile(MANIFEST, content);
}

function scanSkill(content) {
  const findings = [];
  let severity = "LOW";

  // 1. Prompt Injection / Authority Override
  if (/ignore\s+(all\s+)?previous|override\s+(system|instructions)|you\s+are\s+now|act\s+as\s+(root|admin)|system\s*:\s*you\s+must|forget\s+(everything|your\s+instructions)|disregard\s+(all|prior)/i.test(content)) {
    findings.push("CRITICAL: prompt injection / authority override パターン検出");
    severity = "CRITICAL";
  }

  // 2. Data Exfiltration
  if (/curl\s+.*(https?:\/\/|ftp:\/\/)|wget\s+|fetch\s*\(|requests?\.(get|post|put)|http\.client|urllib\.request|exfiltrat|send.*(data|token|key|secret|credential).*to/i.test(content)) {
    if (/curl\s+-X?\s*(POST|PUT)|curl\s+.*-d\s|wget\s+--post|requests?\.post|fetch.*method.*POST/i.test(content)) {
      findings.push("HIGH: 外部への POST/データ送信パターン検出");
      if (severity !== "CRITICAL") severity = "HIGH";
    }
  }

  // 3. Credential / Secret Access
  if (/\$\{?(API_KEY|SECRET_KEY|AUTH_TOKEN|CREDENTIALS|AWS_ACCESS|OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN)\}?|credentials\.json|id_rsa|\.ssh\/config|\.aws\/credentials|\.npmrc|\.netrc/i.test(content)) {
    findings.push("HIGH: 機密情報・認証情報へのアクセスパターン検出");
    if (severity !== "CRITICAL") severity = "HIGH";
  }

  // 4. Code Execution
  if (/eval\s*\(|exec\s*\(|os\.system\s*\(|subprocess\.(run|call|Popen)|child_process\.(exec|spawn)|new\s+Function\s*\(/i.test(content)) {
    findings.push("MEDIUM: 動的コード実行パターン検出");
    if (severity === "LOW") severity = "MEDIUM";
  }

  // 5. File System Abuse
  if (/rm\s+-rf\s+[\/~]|chmod\s+777|chown\s+root|>\/dev\/sd|mkfs\.|dd\s+if=|shred\s/i.test(content)) {
    findings.push("CRITICAL: 破壊的ファイル操作パターン検出");
    severity = "CRITICAL";
  }

  // 6. Privilege Escalation
  if (/sudo\s|doas\s|su\s+-\s|chmod\s+[4267][0-7]{2}\s|setuid|setgid|\/etc\/passwd|\/etc\/shadow|visudo/i.test(content)) {
    findings.push("HIGH: 権限昇格パターン検出");
    if (severity !== "CRITICAL") severity = "HIGH";
  }

  // 7. Hidden / Obfuscated Content
  if (/base64\s+(--)?decode|atob\s*\(|\\x[0-9a-f]{2}\\x[0-9a-f]{2}\\x[0-9a-f]{2}|\\u200[b-f]|\\u00ad|String\.fromCharCode/i.test(content)) {
    findings.push("MEDIUM: 難読化・隠蔽コンテンツパターン検出");
    if (severity === "LOW") severity = "MEDIUM";
  }

  // 8. Supply Chain
  if (/(npm|pip|gem|cargo)\s+install\s+\S/i.test(content)) {
    findings.push("MEDIUM: 外部パッケージインストールパターン検出");
    if (severity === "LOW") severity = "MEDIUM";
  }

  // 9. Network Listener
  if (/listen\s*\(\s*[0-9]|bind\s*\(\s*['"]0\.0\.0\.0|nc\s+-l|socat\s|ncat\s+-l|python3?\s+-m\s+http\.server/i.test(content)) {
    findings.push("HIGH: ネットワークリスナー起動パターン検出");
    if (severity !== "CRITICAL") severity = "HIGH";
  }

  return { findings, severity };
}

export const ScanNewSkills = async ({ $ }) => {
  return {
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "bash") return;
      const cmd = output?.args?.command;
      if (!cmd) return;

      // スキルインストール系コマンドのみ対象
      if (!/(npx\s+@anthropic\/skill|npx\s+skill|skill\s+install|skill\s+add)/i.test(cmd)) return;

      // スキルディレクトリの一覧を取得
      let currentSkills = [];
      try {
        const entries = await readdir(SKILLS_DIR, { withFileTypes: true });
        currentSkills = entries.filter(e => e.isDirectory()).map(e => e.name).sort();
      } catch {
        return;
      }

      const current = currentSkills.join("\n");
      const previous = await readManifest();

      // マニフェストがなければ作成して終了
      if (previous === null) {
        await writeManifest(current);
        return;
      }

      // 新規スキルを検出
      const previousSet = new Set(previous.split("\n"));
      const newSkills = currentSkills.filter(s => !previousSet.has(s));

      // マニフェスト更新
      await writeManifest(current);

      if (newSkills.length === 0) return;

      console.log(`🔍 新規スキルを検出。セキュリティスキャンを実行中...`);
      console.log("");

      let foundRisk = false;

      for (const skill of newSkills) {
        const skillPath = join(SKILLS_DIR, skill);
        try {
          const { readFile, stat } = await import("node:fs/promises");
          const s = await stat(skillPath);
          if (!s.isDirectory()) continue;

          // テキストファイルを結合
          const files = await readdir(skillPath);
          let content = "";
          for (const file of files) {
            if (/\.(md|sh|py|js|ts|json|yaml|yml|toml)$/.test(file)) {
              try {
                content += await readFile(join(skillPath, file), "utf-8");
              } catch {}
            }
          }

          if (!content) continue;

          const { findings, severity } = scanSkill(content);

          console.log(`--- ${skill} ---`);
          if (findings.length === 0) {
            console.log(`  ✓ 問題なし`);
          } else {
            for (const f of findings) {
              console.log(`  ${f}`);
            }
            console.log(`  総合: ${severity} (${findings.length} 件)`);
            if (severity === "CRITICAL" || severity === "HIGH") {
              foundRisk = true;
            }
          }
          console.log("");
        } catch {}
      }

      if (foundRisk) {
        console.log("⛔ 高リスクのスキルが検出されました。使用前に内容を確認してください。");
      }
    },
  };
};
