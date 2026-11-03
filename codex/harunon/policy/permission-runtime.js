import { decidePermission, loadPermissionIntent } from "./permission-intent.js";
import { normalizePermissionEvent, projectHookEffect } from "./permission-targets.js";

/** Return no result only for tools this contract does not yet classify or for the existing PR gate. */
export function evaluateRuntimePermission(target, event, location, options = {}) {
  const normalized = normalizePermissionEvent(target, event, location);
  if (normalized.action === "unresolved" && normalized.reason.startsWith("unmapped")) return undefined;
  const verdict = decidePermission(options.intent ?? loadPermissionIntent(), normalized);
  if (verdict.effect === "delegate") return undefined;
  return {
    effect: verdict.effect === "unresolved" ? "deny" :
      projectHookEffect(target, verdict.effect, options),
    reason: verdict.reason,
  };
}
