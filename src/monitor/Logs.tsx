import { useCallback, useLayoutEffect, useRef, useState } from "react";
import {
  Button,
  Column,
  Grid,
  InlineNotification,
  Stack,
  Tile,
} from "@carbon/react";
import {
  logPath,
  logs,
  reading,
  safeLog,
  type LogGroup,
  type RecordValue,
  type Work,
} from "./model";
import { usePolling, type Observation } from "./use-polling";

export function Evidence({
  observation,
  paused,
}: {
  observation: Observation<unknown>;
  paused: boolean;
}) {
  return (
    <Stack gap={3}>
      <p className="monitor-muted cds--type-label-01">
        {observation.observedAt
          ? `Observed ${new Date(observation.observedAt).toLocaleTimeString()}`
          : "Waiting for an observation"}
        {paused ? " · Live updates paused" : " · Live updates"}
        {observation.error && observation.observedAt
          ? " · Showing retained evidence"
          : ""}
      </p>
      {observation.error && (
        <InlineNotification
          kind="warning"
          title="Observation unavailable"
          subtitle={observation.error}
          hideCloseButton
          role="status"
        />
      )}
    </Stack>
  );
}

function LogWindow({ group, label }: { group: LogGroup; label: string }) {
  const window = useRef<HTMLPreElement>(null);
  const [following, setFollowing] = useState(true);
  useLayoutEffect(() => {
    if (following && window.current)
      window.current.scrollTop = window.current.scrollHeight;
  }, [group, following]);
  return (
    <Tile className="monitor-log-tile">
      <Stack gap={4}>
        <Stack orientation="horizontal" gap={5} className="monitor-toolbar">
          <h3 className="cds--type-heading-compact-01">{label}</h3>
          <Button
            size="sm"
            kind="ghost"
            aria-pressed={following}
            onClick={() => setFollowing(!following)}
          >
            {following ? "Following tail" : "Follow tail"}
          </Button>
        </Stack>
        <p className="cds--type-label-01 monitor-muted">
          {group.lines.length} records · Tail 200 ·{" "}
          {group.truncated
            ? "Truncated by service"
            : "No service truncation reported"}
          {group.truncated &&
            ` · Shortened ${reading(group.truncation.record_truncations)} records · Omitted at least ${reading(group.truncation.omitted_bytes_at_least)} bytes`}
        </p>
        <pre
          ref={window}
          tabIndex={0}
          role="region"
          aria-label={`${label} log records`}
          className="monitor-log-window"
          onScroll={(event) => {
            const target = event.currentTarget;
            setFollowing(
              target.scrollHeight - target.clientHeight - target.scrollTop < 8,
            );
          }}
        >
          {group.marker && `${safeLog(group.marker)}\n`}
          {group.lines.length
            ? group.lines.map(safeLog).join("\n")
            : "No matching records in the bounded log window."}
        </pre>
      </Stack>
    </Tile>
  );
}

export function Logs({
  work,
  paused,
  refresh,
}: {
  work?: Work;
  paused: boolean;
  refresh: number;
}) {
  const kind = work?.kind;
  const id = work?.id;
  const decode = useCallback(
    (payload: RecordValue) =>
      logs(payload, kind && id ? { kind, id } : undefined),
    [kind, id],
  );
  const observation = usePolling(
    logPath(work),
    decode,
    !paused,
    refresh,
    work ? 1000 : 3000,
  );
  return (
    <Stack gap={5}>
      <Evidence observation={observation} paused={paused} />
      {observation.data ? (
        <Grid narrow withRowGap className="monitor-grid monitor-log-grid">
          {observation.data.map((group) => (
            <Column key={group.source} sm={4} md={8} lg={work ? 16 : 8}>
              <LogWindow
                group={group}
                label={
                  work
                    ? `${kind === "job" ? "Job" : "Request"} logs`
                    : group.source === "service"
                      ? "Service logs"
                      : "Qdrant logs"
                }
              />
            </Column>
          ))}
        </Grid>
      ) : (
        <p className="cds--type-body-01 monitor-muted">
          No log observation yet.
        </p>
      )}
    </Stack>
  );
}
