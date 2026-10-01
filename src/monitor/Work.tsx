import { Fragment } from "react";
import {
  DataTable,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableExpandHeader,
  TableExpandRow,
  TableExpandedRow,
  TableHead,
  TableHeader,
  TableRow,
} from "@carbon/react";
import {
  initiator,
  jobProgress,
  reading,
  rootOf,
  text,
  type Activity,
  type Jobs,
  type Work,
} from "./model";
import { Metrics, Status } from "./presentation";
import { DataTree } from "./DataTree";
import { JobControls } from "./JobControls";
import { Logs } from "./Logs";

export function WorkPage({
  kind,
  data,
  paused,
  stale,
  refresh,
  onRefresh,
}: {
  kind: Work["kind"];
  data?: Jobs | Activity;
  paused: boolean;
  stale: boolean;
  refresh: number;
  onRefresh: () => void;
}) {
  const indexing = kind === "job";
  const label = indexing ? "Index Requests" : "Queries";
  const records = data?.records ?? [];
  const counts =
    data && "summary" in data
      ? data.summary
      : data && "counts" in data
        ? data.counts
        : {};
  const rows = records.map((record) => ({
    id: text(record[indexing ? "id" : "request_id"]),
    state: text(record.state),
    identity: indexing ? rootOf(record) : text(record.query, "Query redacted"),
    origin: indexing ? initiator(record) : text(record.source),
    progress: indexing
      ? jobProgress(record)
      : `${reading(record.result_count)} results · ${reading(record.total_seconds, " s")}`,
  }));
  const headers = [
    { key: "state", header: "State" },
    {
      key: "identity",
      header: indexing ? "Repository / request" : "Query / request",
    },
    { key: "origin", header: indexing ? "Initiator" : "Source" },
    { key: "progress", header: indexing ? "Progress" : "Results / duration" },
  ];
  return (
    <Stack gap={5}>
      <Metrics
        counts={counts}
        labels={
          indexing
            ? [
                ["running", "Processing"],
                ["queued", "Queued"],
                ["paused", "Paused"],
                ["succeeded", "Succeeded"],
                ["failed", "Failed"],
              ]
            : [
                ["queued", "Queued"],
                ["active", "Processing"],
                ["recent", "Recently finished"],
                ["total", "Retained queries"],
              ]
        }
      />
      <p className="cds--type-label-01 monitor-muted">
        {records.length} retained {indexing ? "index requests" : "queries"} ·
        Limit 100
      </p>
      <div className="monitor-table-window">
        <DataTable rows={rows} headers={headers} size="lg" isSortable>
          {({ rows, headers, getTableProps, getHeaderProps, getRowProps }) => (
            <Table
              {...getTableProps()}
              aria-label={label}
              className="monitor-work-table"
            >
              <TableHead>
                <TableRow>
                  <TableExpandHeader />
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
                  const record = records.find(
                    (item) => item[indexing ? "id" : "request_id"] === row.id,
                  );
                  if (!record) return null;
                  const { key, ...props } = getRowProps({ row });
                  return (
                    <Fragment key={key}>
                      <TableExpandRow
                        {...props}
                        aria-label={`Expand ${indexing ? "index request" : "query"} ${row.id}`}
                      >
                        <TableCell>
                          <Status
                            state={text(record.outcome, text(record.state))}
                          />
                        </TableCell>
                        <TableCell>
                          <Stack gap={2}>
                            <span>{row.cells[1].value}</span>
                            <span className="cds--type-label-01 monitor-muted">
                              {row.id}
                            </span>
                          </Stack>
                        </TableCell>
                        <TableCell>{row.cells[2].value}</TableCell>
                        <TableCell>{row.cells[3].value}</TableCell>
                      </TableExpandRow>
                      {row.isExpanded && (
                        <TableExpandedRow colSpan={5}>
                          <Stack gap={5} className="monitor-expanded">
                            {indexing && (
                              <JobControls
                                job={record}
                                disabled={paused || stale}
                                onRefresh={onRefresh}
                              />
                            )}
                            <DataTree
                              value={record}
                              label={
                                indexing ? "Index request" : "Query evidence"
                              }
                            />
                            <Logs
                              work={{ kind, id: row.id }}
                              paused={paused}
                              refresh={refresh}
                            />
                          </Stack>
                        </TableExpandedRow>
                      )}
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </DataTable>
        {!rows.length && (
          <p className="monitor-empty">
            No {label.toLowerCase()} in this observation.
          </p>
        )}
      </div>
    </Stack>
  );
}
