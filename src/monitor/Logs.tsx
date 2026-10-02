import { useCallback, useId, useState } from "react";
import {
  Column,
  Grid,
  InlineNotification,
  Stack,
  Pagination,
  Search,
  Select,
  SelectItem,
} from "@carbon/react";
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
        {observation.error
          ? observation.observedAt
            ? "Showing data from the last successful update"
            : ""
          : paused
            ? "Live updates paused"
            : !observation.observedAt
              ? "Loading data…"
              : ""}
      </p>
      {observation.error && (
        <InlineNotification
          lowContrast
          kind="warning"
          title="Unable to update data"
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
    <section className="monitor-log-tile">
      <Stack gap={4}>
        <h3 className="cds--type-heading-compact-01">{label}</h3>
        <p className="cds--type-label-01 monitor-muted">
          {group.lines.length} records on this page{" "}
          {group.truncated ? " · Some log content exceeds the size limit" : ""}
        </p>
        <DataTree
          label={label}
          value={group.lines.map((line) => ({ message: safeLog(line) }))}
        />
      </Stack>
    </section>
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
  const controlId = useId();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("all");
  const [order, setOrder] = useState("asc");
  const offset = (page - 1) * pageSize;
  const decode = useCallback(
    (payload: RecordValue) =>
      logs(payload, kind && id ? { kind, id } : undefined, {
        source,
        lines: pageSize,
        offset,
        contains: search,
        order,
      }),
    [kind, id, source, pageSize, offset, search, order],
  );
  const observation = usePolling(
    logPath(work, { source, lines: pageSize, offset, contains: search, order }),
    decode,
    !paused,
    refresh,
    work ? 1000 : 3000,
  );
  return (
    <Stack gap={5}>
      <Grid narrow className="monitor-grid monitor-list-filters">
        <Column sm={4} md={4} lg={8}>
          <Search
            id={`${controlId}-search`}
            labelText="Filter logs"
            placeholder="Filter log messages"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </Column>
        {!work && (
          <Column sm={2} md={2} lg={4}>
            <Select
              id={`${controlId}-source`}
              labelText="Source"
              value={source}
              onChange={(event) => {
                setSource(event.target.value);
                setPage(1);
              }}
            >
              <SelectItem value="all" text="All sources" />
              <SelectItem value="service" text="Service" />
              <SelectItem value="qdrant" text="Qdrant" />
            </Select>
          </Column>
        )}
        <Column sm={2} md={2} lg={4}>
          <Select
            id={`${controlId}-order`}
            labelText="Order on page"
            value={order}
            onChange={(event) => {
              setOrder(event.target.value);
              setPage(1);
            }}
          >
            <SelectItem value="asc" text="Oldest first" />
            <SelectItem value="desc" text="Newest first" />
          </Select>
        </Column>
      </Grid>
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
        <p className="cds--type-body-01 monitor-muted">No logs loaded yet.</p>
      )}
      <Pagination
        page={page}
        pageSize={pageSize}
        pageSizes={[10, 25, 50, 100, 200]}
        totalItems={Math.max(
          0,
          ...(observation.data ?? []).map((group) => group.matched),
        )}
        itemsPerPageText="Lines per source"
        forwardText="Older log records"
        backwardText="Newer log records"
        onChange={({ page: nextPage, pageSize: nextSize }) => {
          setPage(nextSize === pageSize ? nextPage : 1);
          setPageSize(nextSize);
        }}
      />
      <p className="cds--type-label-01 monitor-muted">
        Page 1 contains the latest matching logs. Older pages cover the
        available log history.
      </p>
    </Stack>
  );
}
