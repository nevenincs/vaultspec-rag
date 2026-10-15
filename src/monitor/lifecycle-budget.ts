/**
 * How long the monitor waits on each service lifecycle verb.
 *
 * The one place a lifecycle wait is stated for the monitor: the server side
 * bounds the owner command it spawns, and the browser bounds the request it
 * sends through that server. Both read the same budget, so the two layers
 * cannot drift apart and a verb's wait is changed in one place.
 *
 * The budgets are the owner's own, by term. A start from a release whose
 * managed runtime is absent probes the accelerator, builds that runtime by
 * downloading the GPU stack, fetches every configured model repository, the
 * Qdrant server binary and this release's monitor, and only then waits for
 * the daemon to serve; the terms below are those steps' own limits, summed
 * because a first start on a host runs all of them in sequence. A stop
 * provisions nothing, so its budget is the termination escalations alone.
 *
 * One term is stated at its widest rather than at what this host will
 * actually do: every model repository a build can configure is counted. The
 * daemon readiness term follows the window an operator sets, which the
 * monitor's server reads from the environment it launches the owner in and
 * reports with the lifecycle state, so the page waits what the server does.
 * Waiting longer than the owner
 * can run costs nothing - the owner answers with its own outcome first -
 * while waiting less kills a start that was still working, after the stop
 * that preceded it already succeeded. A check in the owner's own tests holds
 * these budgets to the ones the owner computes.
 */

const second = 1000;

/** The accelerator probe in the service interpreter, before any fetch. */
const acceleratorProbe = 60 * second;

/** One build of the managed runtime: lock wait, then its two uv steps. */
const runtimeBuild = (20 + 300 + 3600) * second;

/**
 * One model repository's fetch, bounded by progress rather than size: the
 * wait for another process holding the cache, the wait for a first byte, one
 * window of too little progress, and the confirmation of the kill.
 */
const modelFetch = (3600 + 60 + 600 + 10) * second;

/** Every model repository a build can configure: dense, sparse, reranker. */
const modelRepositories = 3;

/** The Qdrant server binary: lock wait, then one whole download. */
const qdrantDownload = (960 + 900) * second;

/** This release's monitor: one whole download. */
const monitorDownload = 2700 * second;

/** The readiness window the service waits out when nothing raises it. */
export const defaultReadinessWindowSeconds = 300;

/**
 * The daemon readiness wait for a *readinessWindowSeconds* window: the store
 * readiness ceiling, which is a multiple of that window, and the import,
 * binary resolution and model load the daemon does around it.
 */
function daemonReadiness(readinessWindowSeconds: number): number {
  return (readinessWindowSeconds * 4 + 300) * second;
}

/** The termination escalations one stop can run, with their exit waits. */
const stopEscalations = 3 * (45 + 5) * second;

/** What the monitor allows each lifecycle verb, in milliseconds. */
export function lifecycleBudgetMilliseconds(
  readinessWindowSeconds: number = defaultReadinessWindowSeconds,
): { start: number; stop: number; restart: number } {
  const start =
    acceleratorProbe +
    runtimeBuild +
    modelFetch * modelRepositories +
    qdrantDownload +
    monitorDownload +
    daemonReadiness(readinessWindowSeconds);
  // A restart is a stop and then a start, each with its own budget.
  return { start, stop: stopEscalations, restart: start + stopEscalations };
}

/**
 * What the browser adds to a server budget for its own round trip, in
 * milliseconds. The browser must outlast the server it is waiting on, so the
 * server's own timeout is the outcome it reports rather than a bare abort.
 */
export const clientMarginMilliseconds = 5 * second;

/**
 * What the page waits on *action*, in milliseconds: the wait the monitor's
 * server reported with the lifecycle state, which follows the readiness
 * window the operator set, and the default only before it has reported.
 */
export function pageBudgetMilliseconds(
  action: string,
  served: unknown,
): number {
  // Pause, resume and stop all end in the monitor's stop-shaped budget.
  const verb = action === "restart" || action === "start" ? action : "stop";
  const reported =
    typeof served === "object" && served !== null
      ? (served as Record<string, unknown>)[verb]
      : undefined;
  return typeof reported === "number" &&
    Number.isFinite(reported) &&
    reported > 0
    ? reported
    : lifecycleBudgetMilliseconds()[verb];
}
