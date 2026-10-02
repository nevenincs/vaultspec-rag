import { useEffect, useState } from "react";
import { request, type RecordValue } from "./model";

export type Observation<T> = { data?: T; observedAt?: number; error?: string };
type StoredObservation<T> = Observation<T> & { path: string };

/** One bounded, non-overlapping observer. Scope changes cancel the old owner. */
export function usePolling<T>(
  path: string,
  decode: (payload: RecordValue) => T,
  enabled: boolean,
  refresh: number,
  interval = 2000,
  timeout = 7000,
): Observation<T> {
  const [stored, setStored] = useState<StoredObservation<T>>({ path });
  useEffect(() => {
    if (!enabled) return;
    let controller: AbortController | undefined;
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (!current || document.hidden || controller) return;
      const active = new AbortController();
      controller = active;
      try {
        const payload = await request(path, { signal: active.signal }, timeout);
        const data = decode(payload);
        if (current && !active.signal.aborted)
          setStored({ path, data, observedAt: Date.now() });
      } catch (error) {
        if (current && !active.signal.aborted) {
          setStored((prior) => ({
            ...(prior.path === path ? prior : {}),
            path,
            error:
              error instanceof Error
                ? error.message
                : "Unable to load data from the service.",
          }));
        }
      } finally {
        controller = undefined;
        if (current && !document.hidden)
          timer = setTimeout(
            () => void poll(),
            active.signal.aborted ? 0 : interval,
          );
      }
    };
    const visibility = () => {
      clearTimeout(timer);
      if (document.hidden) controller?.abort();
      else void poll();
    };
    document.addEventListener("visibilitychange", visibility);
    void poll();
    return () => {
      current = false;
      controller?.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [path, decode, enabled, refresh, interval, timeout]);
  return stored.path === path ? stored : {};
}
