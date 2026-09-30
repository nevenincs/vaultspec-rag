import {
  Button,
  DataTable,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@carbon/react";
import {
  initiator,
  jobProgress,
  object,
  reading,
  rootOf,
  text,
  type Activity,
  type Jobs,
  type RecordValue,
  type Work,
} from "./model";
import { Metrics, Status } from "./presentation";
function WorkTable({
  kind,
  records,
  selected,
  onInspect,
}: {
  kind: Work["kind"];
  records: RecordValue[];
  selected: Work | null;
  onInspect: (work: Work) => void;
}) {
  const indexing = kind === "job";
  const label = indexing ? "Indexing jobs" : "Serving requests";
  const byId = new Map(
    records.map((record) => [
      text(record[indexing ? "id" : "request_id"], ""),
      record,
    ]),
  );
  const headers = [
    { key: "state", header: "State" },
    { key: "identity", header: indexing ? "Job / project" : "Query / request" },
    { key: "origin", header: indexing ? "Initiator" : "Source" },
    { key: "progress", header: indexing ? "Progress" : "Outcome" },
    { key: "inspect", header: "Inspect" },
  ];
  const tableRows = records.map((record) => ({
    id: text(record[indexing ? "id" : "request_id"], ""),
    state: text(record.state),
    identity: indexing ? rootOf(record) : text(record.query),
    origin: indexing ? initiator(record) : text(record.source),
    progress: indexing ? jobProgress(record) : text(record.outcome),
    inspect: "Inspect",
  }));
  return (
    <div
      className="monitor-table-window"
      role="region"
      aria-label={`${label}, horizontally scrollable`}
      tabIndex={0}
    >
      <DataTable rows={tableRows} headers={headers} size="lg">
        {({ rows, headers, getTableProps, getHeaderProps, getRowProps }) => (
          <Table
            {...getTableProps()}
            aria-label={label}
            className="monitor-work-table"
          >
            <TableHead>
              <TableRow>
                {headers.map((header) => {
                  const { key, ...props } = getHeaderProps({ header });
                  return (
                    <TableHeader key={key} {...props}>
                      {header.header}
                    </TableHeader>
                  );
                })}
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => {
                const id = row.id;
                const record = byId.get(id)!;
                const { key, ...props } = getRowProps({ row });
                const state = text(record.state, "unknown");
                const chosen = selected?.kind === kind && selected.id === id;
                return (
                  <TableRow key={key} {...props} data-selected={chosen}>
                    <TableCell>
                      <Stack gap={2}>
                        <Status
                          state={text(record.outcome, state)}
                          label={
                            state === "terminal"
                              ? text(record.outcome, "finished")
                              : state
                          }
                        />
                        {indexing && record.stalled === true && (
                          <Status state="stalled" />
                        )}
                        {indexing &&
                          typeof record.desired_state === "string" &&
                          record.desired_state !== state && (
                            <span className="cds--type-label-01">
                              Requested {record.desired_state}
                            </span>
                          )}
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <Stack gap={2}>
                        <p className="cds--type-body-compact-01">
                          {indexing
                            ? text(
                                record.source,
                                text(object(record.spec).source),
                              )
                            : text(
                                record.query,
                                record.query_redacted === true
                                  ? "Query redacted by service"
                                  : "Query not reported",
                              )}
                        </p>
                        <p className="cds--type-label-01 monitor-muted">
                          {indexing ? rootOf(record) : id}
                        </p>
                        {indexing && (
                          <p className="cds--type-label-01 monitor-muted">
                            {id}
                          </p>
                        )}
                        {!indexing && record.query_truncated === true && (
                          <p className="cds--type-label-01">
                            Query truncated by service
                          </p>
                        )}
                      </Stack>
                    </TableCell>
                    <TableCell>
                      {indexing ? initiator(record) : text(record.source)}
                    </TableCell>
                    <TableCell>
                      <Stack gap={2}>
                        <p>
                          {indexing
                            ? jobProgress(record)
                            : state === "queued"
                              ? "Waiting for admission"
                              : state === "active"
                                ? "Processing"
                                : `${reading(record.total_seconds, " s")} · HTTP ${reading(record.status_code)}`}
                        </p>
                        <p className="cds--type-label-01 monitor-muted">
                          {indexing
                            ? `Runtime ${reading(record.runtime_seconds, " s")}`
                            : `${reading(record.result_count)} results`}
                        </p>
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <Button
                        kind="ghost"
                        size="sm"
                        aria-label={`Inspect ${kind} ${id}`}
                        aria-pressed={chosen}
                        onClick={() => onInspect({ kind, id })}
                      >
                        {chosen ? "Selected" : "Inspect"}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </DataTable>
      {records.length === 0 && (
        <p className="monitor-empty cds--type-body-01">
          No {indexing ? "indexing jobs" : "serving requests"} in this
          observation.
        </p>
      )}
    </div>
  );
}

export function JobLane({
  data,
  selected,
  onInspect,
}: {
  data?: Jobs;
  selected: Work | null;
  onInspect: (work: Work) => void;
}) {
  return (
    <Stack gap={5}>
      <Metrics
        counts={data?.summary ?? {}}
        labels={[
          ["running", "Processing"],
          ["queued", "Queued"],
          ["paused", "Paused"],
          ["terminal", "Finished"],
          ["succeeded", "Succeeded"],
          ["failed", "Failed"],
          ["stalled", "Stalled"],
        ]}
      />
      <p className="cds--type-label-01 monitor-muted">
        Showing {data?.records.length ?? "—"} of {data?.total ?? "—"} retained
        jobs · Page limit 100 · Counts cover the service's retained job
        snapshot.
      </p>
      {data && (
        <WorkTable
          kind="job"
          records={data.records}
          selected={selected}
          onInspect={onInspect}
        />
      )}
    </Stack>
  );
}

export function RequestLane({
  data,
  selected,
  onInspect,
}: {
  data?: Activity;
  selected: Work | null;
  onInspect: (work: Work) => void;
}) {
  return (
    <Stack gap={5}>
      <Metrics
        counts={data?.counts ?? {}}
        labels={[
          ["queued", "Queued"],
          ["active", "Processing"],
          ["recent", "Recently finished"],
          ["total", "Retained requests"],
        ]}
      />
      <p className="cds--type-label-01 monitor-muted">
        Showing {data?.returned ?? "—"} requests · Page limit 100 · Queued and
        active first, followed by bounded recent history.
      </p>
      {data && (
        <WorkTable
          kind="request"
          records={data.records}
          selected={selected}
          onInspect={onInspect}
        />
      )}
    </Stack>
  );
}
