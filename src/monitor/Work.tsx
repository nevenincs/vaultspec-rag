import { Fragment, useEffect, useState } from "react";
import {
  DataTable,
  Accordion,
  AccordionItem,
  Pagination,
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
import { RequestDetails } from "./RequestDetails";
import { ListFilters, type ListOptions } from "./ListFilters";
import { JobControls } from "./JobControls";
import { Logs } from "./Logs";

export function WorkPage({
  kind,
  data,
  paused,
  stale,
  refresh,
  onRefresh,
  options,
  onOptionsChange,
}: {
  kind: Work["kind"];
  data?: Jobs | Activity;
  paused: boolean;
  stale: boolean;
  refresh: number;
  onRefresh: () => void;
  options: ListOptions;
  onOptionsChange: (options: ListOptions) => void;
}) {
  const [mobile, setMobile] = useState(
    () => matchMedia("(max-width: 41.98rem)").matches,
  );
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const toggle = (id: string) =>
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  useEffect(() => {
    const media = matchMedia("(max-width: 41.98rem)");
    const change = () => setMobile(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
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
  const detail = (record: (typeof records)[number], identity: string) => (
    <Stack gap={5} className="monitor-expanded">
      {indexing && (
        <JobControls
          job={record}
          disabled={paused || stale}
          onRefresh={onRefresh}
        />
      )}
      <RequestDetails record={record} kind={kind} />
      <Logs work={{ kind, id: identity }} paused={paused} refresh={refresh} />
    </Stack>
  );
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
      <ListFilters
        id={indexing ? "index-requests" : "queries"}
        options={options}
        onChange={onOptionsChange}
        placeholder={
          indexing
            ? "Search requests or repositories"
            : "Search queries or repositories"
        }
        states={(indexing
          ? [
              "queued",
              "running",
              "pausing",
              "paused",
              "cancelling",
              "succeeded",
              "failed",
              "cancelled",
              "interrupted",
            ]
          : ["queued", "active", "terminal"]
        ).map((state) => [
          state,
          state === "terminal"
            ? "Finished"
            : state.replace(/^./, (letter) => letter.toUpperCase()),
        ])}
        sorts={
          indexing
            ? [
                ["priority", "Status priority"],
                ["created_at", "Created"],
                ["updated_at", "Last updated"],
                ["root", "Repository"],
                ["state", "Status"],
              ]
            : [
                ["priority", "Status priority"],
                ["started_at", "Started"],
                ["query", "Query"],
                ["total_seconds", "Duration"],
                ["state", "Status"],
              ]
        }
      />
      {mobile ? (
        <Accordion size="lg" className="monitor-mobile-work">
          {rows.map((row) => {
            const record = records.find(
              (item) => item[indexing ? "id" : "request_id"] === row.id,
            )!;
            return (
              <AccordionItem
                key={row.id}
                data-work-id={row.id}
                open={expanded.has(row.id)}
                onHeadingClick={() => toggle(row.id)}
                title={
                  <Stack gap={3} className="monitor-work-title">
                    <Status state={text(record.outcome, row.state)} />
                    <span>{row.identity}</span>
                    <span className="cds--type-label-01">
                      {row.origin} · {row.progress}
                    </span>
                  </Stack>
                }
              >
                {expanded.has(row.id) && detail(record, row.id)}
              </AccordionItem>
            );
          })}
        </Accordion>
      ) : (
        <div className="monitor-table-window monitor-desktop-work">
          <DataTable rows={rows} headers={headers} size="lg">
            {({
              rows,
              headers,
              getTableProps,
              getHeaderProps,
              getRowProps,
            }) => (
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
                          isExpanded={expanded.has(row.id)}
                          onExpand={() => toggle(row.id)}
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
                        {expanded.has(row.id) && (
                          <TableExpandedRow
                            colSpan={5}
                            className="monitor-request-expansion"
                          >
                            {detail(record, row.id)}
                          </TableExpandedRow>
                        )}
                      </Fragment>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </DataTable>
        </div>
      )}
      {!rows.length && (
        <p className="monitor-empty">No {label.toLowerCase()} to show.</p>
      )}
      <Pagination
        className="monitor-work-pagination"
        id={`${kind}-pagination`}
        page={options.page}
        pageSize={options.pageSize}
        pageSizes={[10, 25, 50, 100]}
        totalItems={data?.matched ?? records.length}
        itemsPerPageText="Requests per page"
        onChange={({ page, pageSize }) =>
          onOptionsChange({
            ...options,
            page: pageSize === options.pageSize ? page : 1,
            pageSize,
          })
        }
      />
    </Stack>
  );
}
