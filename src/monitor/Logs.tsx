import { useCallback } from "react";
import { Column, Grid, InlineNotification, Stack, Tile } from "@carbon/react";
import {
  logPath,
  logs,
  safeLog,
  type LogGroup,
  type RecordValue,
  type Work,
} from "./model";
import { DataTree } from "./DataTree";
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
        {observation.error && observation.observedAt
          ? "Showing retained evidence"
          : paused
            ? "Live updates paused"
            : !observation.observedAt
              ? "Waiting for an observation"
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
  return (
    <Tile className="monitor-log-tile">
      <Stack gap={4}>
        <h3 className="cds--type-heading-compact-01">{label}</h3>
        <p className="cds--type-label-01 monitor-muted">
          {group.lines.length} records · Tail 200 ·{" "}
          {group.truncated
            ? "Truncated by service"
            : "No service truncation reported"}
        </p>
        <DataTree
          label={label}
          initialPath={["records"]}
          value={{
            source: group.source,
            records: group.lines.map((line, index) => ({
              record: index + 1,
              message: safeLog(line),
            })),
            ...(group.truncated
              ? { marker: safeLog(group.marker), truncation: group.truncation }
              : {}),
          }}
        />
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
                    ? `${kind === "job" ? "Index request" : "Query"} logs`
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
