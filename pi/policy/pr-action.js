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
}

/**
 * Tokenize just enough shell syntax to identify direct command positions. This is
 * deliberately not a shell interpreter: dynamic command names, eval/xargs, and
 * other dispatch mechanisms remain outside the recognizer's contract.
 */
function tokenize(command) {
  const tokens = [];
  const word = { value: "", started: false };
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

function actionForCommand(tokens) {
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

  if (tokens[index]?.value === "rtk") {
    index += 1;
  }
  if (tokens[index]?.value !== "gh" || tokens[index + 1]?.value !== "pr") return undefined;
  const action = tokens[index + 2]?.value;
  if (action === "create") return "pr.create";
  if (action === "merge") return "pr.merge";
  return undefined;
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
        actionCount += 1;
        onlyAction = action;
      }
      segment = [];
      continue;
    }
    segment.push(token);
  }

  const action = actionForCommand(segment);
  if (action) {
    actionCount += 1;
    onlyAction = action;
  }
  if (actionCount > 1) return AMBIGUOUS_PR_ACTION;
  return onlyAction;
}
