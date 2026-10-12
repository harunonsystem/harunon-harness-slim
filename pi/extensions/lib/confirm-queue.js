// Pi has one editor dialog slot. Concurrent tool calls must not replace an
// unanswered confirmation with a later one. This queue is process-local and
// records no grants: every call still gets its own decision.
export function createConfirmationQueue(timeoutMs = 120_000, watchdogGraceMs = 1_000) {
  const pending = [];
  let active;
  let disabled = false;

  function settle(job, approved) {
    if (job.settled) return;
    job.settled = true;
    job.signal?.removeEventListener("abort", job.onAbort);
    job.resolve(approved);
  }

  function stopAll() {
    disabled = true;
    if (active) {
      active.dialogAbort.abort();
      clearTimeout(active.timer);
      settle(active, false);
      active = undefined;
    }
    for (const job of pending.splice(0)) settle(job, false);
  }

  function release(job, approved) {
    clearTimeout(job.timer);
    settle(job, approved);
    if (active === job) {
      active = undefined;
      queueMicrotask(pump);
    }
  }

  function pump() {
    if (disabled || active) return;
    const job = pending.shift();
    if (!job) return;
    if (job.settled || job.signal?.aborted) {
      settle(job, false);
      queueMicrotask(pump);
      return;
    }
    active = job;
    // Pi's timeout dismisses the actual dialog. If its promise still does not
    // settle, close the whole queue instead of displaying another dialog over it.
    job.timer = setTimeout(stopAll, timeoutMs + watchdogGraceMs);
    try {
      Promise.resolve(job.ctx.ui.confirm(job.title, job.message, {
        timeout: timeoutMs,
        signal: job.dialogAbort.signal,
      })).then((approved) => release(job, approved === true), () => release(job, false));
    } catch {
      release(job, false);
    }
  }

  const confirm = (ctx, title, message) => {
    if (disabled || !ctx.hasUI || ctx.signal?.aborted) return Promise.resolve(false);
    return new Promise((resolve) => {
      const job = { ctx, title, message, signal: ctx.signal, resolve,
        settled: false, dialogAbort: new AbortController() };
      job.onAbort = () => {
        if (active === job) {
          // Resolve the cancelled call immediately, but retain the UI slot
          // until Pi reports that its dialog has actually closed.
          settle(job, false);
          job.dialogAbort.abort();
          clearTimeout(job.timer);
          job.timer = setTimeout(stopAll, watchdogGraceMs);
        } else {
          settle(job, false);
          const index = pending.indexOf(job);
          if (index !== -1) pending.splice(index, 1);
        }
      };
      job.signal?.addEventListener("abort", job.onAbort, { once: true });
      pending.push(job);
      pump();
    });
  };
  confirm.close = stopAll;
  return confirm;
}

// Pi loads each extension with a separate Jiti module cache. A module-local
// singleton would create one queue per extension and allow dialogs to collide.
const QUEUE_KEY = Symbol.for("harunon-harness.pi.confirm-queue");

function sharedQueue() {
  return globalThis[QUEUE_KEY] ??= createConfirmationQueue();
}

export function shutdownConfirmationQueue() {
  sharedQueue().close();
}

export function startConfirmationQueue() {
  globalThis[QUEUE_KEY]?.close();
  globalThis[QUEUE_KEY] = createConfirmationQueue();
}

export function serializedConfirmContext(ctx) {
  return {
    cwd: ctx.cwd,
    hasUI: ctx.hasUI,
    ui: {
      confirm: (title, message) => sharedQueue()(ctx, title, message),
      notify: (message, level) => ctx.ui.notify(message, level),
    },
  };
}
