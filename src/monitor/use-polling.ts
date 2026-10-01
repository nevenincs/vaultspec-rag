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
    const controller = new AbortController();
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const payload = await request(
          path,
          { signal: controller.signal },
          timeout,
        );
        const data = decode(payload);
        if (current) setStored({ path, data, observedAt: Date.now() });
      } catch (error) {
        if (current) {
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
        if (current) timer = setTimeout(() => void poll(), interval);
      }
    };
    void poll();
    return () => {
      current = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, decode, enabled, refresh, interval, timeout]);
  return stored.path === path ? stored : {};
}
