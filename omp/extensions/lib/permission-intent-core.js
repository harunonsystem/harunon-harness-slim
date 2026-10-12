/** OMP entry point for the shared tool_call permission adapter. */
import { createPermissionIntentHandler } from "../../policy/permission-tool-call.js";
export { createPermissionIntentHandler };

export function ompPermissionIntent(pi) {
  pi.on("tool_call", createPermissionIntentHandler("omp"));
}
