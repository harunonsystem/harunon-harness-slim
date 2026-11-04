const ACTION_AMBIGUOUS = "pr.ambiguous";
const SEPARATOR_VALUES = new Set([";", "&&", "||", "|", "&", "(", ")", "\n"]);
const ENV_ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const SIMPLE_WRAPPERS = new Set([
  "!",
  "builtin",
  "command",
  "declare",
  "do",
  "elif",
  "else",
  "env",
  "exec",
  "export",
  "if",
  "local",
  "nice",
  "nohup",
  "readonly",
  "sudo",
  "then",
  "time",
  "typeset",
  "until",
  "while",
]);
const SHELL_COMMAND_WRAPPERS = new Set(["bash", "sh", "zsh", "dash", "ksh"]);
const WRAPPER_OPTIONS_WITH_VALUES = new Map([
  ["env", new Set(["-C", "--chdir", "-u", "--unset"])],
  ["nice", new Set(["-n", "--adjustment"])],
  ["sudo", new Set(["-C", "-u", "--user"])],
]);

/**
 * Marker returned when a direct command contains more than one PR action.
 * Callers must block this case rather than authorizing whichever action appears first.
 */
export const AMBIGUOUS_PR_ACTION = ACTION_AMBIGUOUS;

function pushWord(tokens, word) {
  if (word.value.length > 0 || word.started) tokens.push({ ...word });
  word.value = "";
  word.started = false;
  word.dynamic = false;
  word.glob = false;
}

/**
 * Tokenize just enough shell syntax to identify direct command positions. This is
 * deliberately not a shell interpreter: dynamic command names, eval/xargs, and
 * other dispatch mechanisms remain outside the recognizer's contract.
 * A literal `bash/sh -c` script is classified recursively; dynamic scripts
 * (`$` expansion), heredocs and eval/xargs stay outside the contract.
 */
export function tokenizeShellCommand(command) {
  return tokenize(command, true);
}

function tokenize(command, splitRedirections = false) {
  const tokens = [];
  // glob: 引用符・エスケープの外に shell が展開する glob 文字がある
  const word = { value: "", started: false, dynamic: false, glob: false };
  let quote;

  for (let index = 0; index < command.length; index += 1) {
    const character = command[index];

    if (quote === "'") {
      if (character === "'") quote = undefined;
      else word.value += character;
      word.started = true;
      continue;
    }

    if (quote === '"') {
      if (character === '"') {
        quote = undefined;
      } else if (character === "\\" && index + 1 < command.length) {
        word.value += command[index + 1];
        word.started = true;
        index += 1;
      } else {
        if (character === "$" || character === "`") word.dynamic = true;
        word.value += character;
        word.started = true;
      }
      continue;
    }

    if (character === "'" || character === '"') {
      quote = character;
      word.started = true;
      continue;
    }

    if (character === "\\") {
      if (index + 1 >= command.length) return undefined;
      if (command[index + 1] === "\n") {
        index += 1;
        continue;
      }
      if (command[index + 1] === "\r") {
        index += 1;
        if (command[index + 1] === "\n") index += 1;
        continue;
      }
      word.value += command[index + 1];
      word.started = true;
      index += 1;
      continue;
    }

    if (character === "\n" || character === "\r") {
      pushWord(tokens, word);
      tokens.push({ value: "\n", separator: true });
      continue;
    }
    if (/\s/.test(character)) {
      pushWord(tokens, word);
      continue;
    }

    if (character === ";" || character === "&" || character === "|") {
      pushWord(tokens, word);
      const next = command[index + 1];
      const value = next === character && character !== ";" ? character + next : character;
      tokens.push({ value, separator: true });
      if (value.length === 2) index += 1;
      continue;
    }

    if (character === "(" || character === ")") {
      pushWord(tokens, word);
      tokens.push({ value: character, separator: true });
      continue;
    }

    if (splitRedirections && (character === "<" || character === ">")) {
      pushWord(tokens, word);
      tokens.push({ value: character, redirection: true });
      continue;
    }
    if (character === "$" || character === "`") word.dynamic = true;
    if ("*?[]{}".includes(character)) word.glob = true;
    word.value += character;
    word.started = true;
  }

  if (quote) return undefined;
  pushWord(tokens, word);
  return tokens;
}

function skipWrapperOptions(tokens, index, wrapper) {
  const valueOptions = WRAPPER_OPTIONS_WITH_VALUES.get(wrapper);
  while (index < tokens.length) {
    const value = tokens[index].value;
    if (tokens[index].separator) return index;
    if (ENV_ASSIGNMENT.test(value)) {
      index += 1;
      continue;
    }
    if (value === "--") return index + 1;
    if (!value.startsWith("-")) return index;
    const option = value.split("=", 1)[0];
    index += 1;
    if (valueOptions?.has(option) && !value.includes("=")) index += 1;
  }
  return index;
}

// `bash -c SCRIPT` の SCRIPT token。script は必ずオプション（-c / -lc / -ec 等）の後ろ。
function shellScriptToken(tokens, index) {
  while (index < tokens.length) {
    const token = tokens[index];
    if (token.separator) return undefined;
    const value = token.value;
    if (value === "--") return undefined;
    if (!value.startsWith("-")) return undefined;
    index += 1;
    // `-c --` や `-c -e` のように直後が option なら bash は後ろの語を script にする。確定できないので返さない
    if (/^-[A-Za-z]*c[A-Za-z]*$/.test(value)) return tokens[index]?.value.startsWith("-") ? undefined : tokens[index];
  }
  return undefined;
}

// env 代入と単純 wrapper を飛ばした command 位置。separator に当たれば undefined。
function commandIndex(tokens) {
  let index = 0;
  while (index < tokens.length) {
    const token = tokens[index];
    if (token.separator) return undefined;
    if (ENV_ASSIGNMENT.test(token.value)) {
      index += 1;
      continue;
    }
    if (!SIMPLE_WRAPPERS.has(token.value)) break;
    const wrapper = token.value;
    index += 1;
    index = skipWrapperOptions(tokens, index, wrapper);
  }
  return index;
}

// literal な `bash -c SCRIPT` の SCRIPT 文字列。shell wrapper でなければ undefined、dynamic なら null。
function literalShellScript(tokens, index) {
  if (!SHELL_COMMAND_WRAPPERS.has(tokens[index]?.value)) return undefined;
  const script = shellScriptToken(tokens, index + 1);
  return script && !script.dynamic ? script.value : null;
}

function directPrTokens(tokens) {
  const index = commandIndex(tokens);
  if (index === undefined) return undefined;
  const script = literalShellScript(tokens, index);
  if (script !== undefined) {
    // 本文を取り出せるのは区切りのない単独の gh pr だけ。分類は classifyPrCommand が再帰で行う。
    const inner = script === null ? undefined : tokenize(script);
    return inner && !inner.some((token) => token.separator) ? directPrTokens(inner) : undefined;
  }
  return directPrTokensAt(tokens, index);
}

function directPrTokensAt(tokens, index) {
  if (tokens[index]?.value === "rtk") {
    index += 1;
  }
  if (tokens[index]?.value !== "gh" || tokens[index + 1]?.value !== "pr") return undefined;
  return tokens.slice(index + 2);
}

const BODY_OPTION = /^(?:--body(?:-file)?(?:=|$)|-[bF])/;
const PR_MUTATIONS = new Set(["create", "edit", "merge"]);
const PR_MUTATION_TEXT = /\bgh\b[\s\S]*\bpr\s+(?:create|edit|merge)\b/;
const isGh = (value) => value.replace(/^\\/, "").split("/").pop() === "gh";

// 直接の gh pr として読めなかった形（未知の wrapper option、`bash -o x -c`、`timeout N` 等）の
// 中に PR の変更操作が見えるか。見えれば分類できないものとして止める（fail closed、2026-11-04）。
// 1 つの引用 token に収まった文字列（echo 'gh pr create' 等）は shell の script 位置でなければデータ。
// echo / printf は引数を表示するだけなので、引用しない `echo gh pr create` もデータ。
const DATA_COMMANDS = new Set(["echo", "printf"]);
function hidesPrMutation(tokens) {
  const values = tokens.map((token) => token.value);
  if (DATA_COMMANDS.has(values[commandIndex(tokens) ?? -1])) return false;
  // /usr/bin/gh 等のパス指定も gh。gh の後ろの pr はすべて見る
  const gh = values.findIndex(isGh);
  if (gh >= 0 && values.some((value, i) => i > gh && value === "pr" && PR_MUTATIONS.has(values[i + 1]))) return true;
  const index = commandIndex(tokens);
  return index !== undefined && SHELL_COMMAND_WRAPPERS.has(values[index]) &&
    values.slice(index + 1).some((value) => PR_MUTATION_TEXT.test(value));
}

function actionForCommand(tokens) {
  const index = commandIndex(tokens);
  const script = index === undefined ? undefined : literalShellScript(tokens, index);
  if (script) return classifyPrCommand(script);
  const args = directPrTokens(tokens);
  if (args === undefined) return hidesPrMutation(tokens) ? AMBIGUOUS_PR_ACTION : undefined;
  const action = args?.[0]?.value;
  if (action === "create") return "pr.create";
  if (action === "merge") return "pr.merge";
  if (action === "edit" && args.slice(1).some((token) => BODY_OPTION.test(token.value))) return "pr.update-body";
  return undefined;
}

/** Exact supported authored input. Never execute shell substitutions or guess --fill/stdin. */
export function publicationInput(command) {
  const tokens = tokenize(command);
  if (!tokens || tokens.some((token) => token.separator)) return { bodyError: "Use one literal gh pr command with --body or --body-file" };
  const args = directPrTokens(tokens);
  if (!args) return { bodyError: "Unsupported publication command" };
  const choices = [];
  for (let index = 1; index < args.length; index += 1) {
    const token = args[index];
    if (!BODY_OPTION.test(token.value)) continue;
    let value;
    let dynamic = token.dynamic;
    const file = token.value.startsWith("--body-file") || token.value.startsWith("-F");
    if (["--body", "--body-file", "-b", "-F"].includes(token.value)) {
      value = args[++index]?.value;
      dynamic ||= args[index]?.dynamic;
    } else {
      value = token.value.startsWith("--") ? token.value.slice(token.value.indexOf("=") + 1) : token.value.slice(2).replace(/^=/, "");
    }
    if (value === undefined || dynamic || (file && ["-", "/dev/stdin"].includes(value))) return { bodyError: "Final body must be literal UTF-8; --fill/stdin/dynamic body is unavailable" };
    choices.push(file ? { bodyFile: value } : { body: value });
  }
  if (choices.length !== 1) return { bodyError: "Specify exactly one final --body or --body-file" };
  // wrapper（env -C、sudo -D、bash -c 内の cd 等）は cwd を変え得るので、gate が読む本文ファイルと
  // gh が送るファイルが別物になる。option の綴りを追わず、直接の gh pr 以外では絶対パスを求める
  const index = commandIndex(tokens);
  const direct = index !== undefined && tokens.slice(0, index).every((token) => ENV_ASSIGNMENT.test(token.value)) &&
    literalShellScript(tokens, index) === undefined;
  if (choices[0].bodyFile !== undefined && !choices[0].bodyFile.startsWith("/") && !direct) {
    return { bodyError: "Use an absolute --body-file path when gh runs through a wrapper (env, sudo, bash -c, ...)" };
  }
  const target = args[1]?.value;
  return { ...choices[0], ...(args[0].value === "edit" ? { number: target } : {}) };
}

/**
 * Return one direct PR action, AMBIGUOUS_PR_ACTION for multiple actions, or
 * undefined when the command is not a supported direct PR invocation.
 */
export function classifyPrCommand(command) {
  if (typeof command !== "string") return undefined;
  const tokens = tokenize(command);
  if (!tokens) return undefined;

  let segment = [];
  let actionCount = 0;
  let onlyAction;

  for (const token of tokens) {
    if (token.separator && SEPARATOR_VALUES.has(token.value)) {
      const action = actionForCommand(segment);
      if (action) {
        actionCount += action === AMBIGUOUS_PR_ACTION ? 2 : 1;
        onlyAction = action;
      }
      segment = [];
      continue;
    }
    segment.push(token);
  }

  const action = actionForCommand(segment);
  if (action) {
    actionCount += action === AMBIGUOUS_PR_ACTION ? 2 : 1;
    onlyAction = action;
  }
  if (actionCount > 1) return AMBIGUOUS_PR_ACTION;
  return onlyAction;
}
