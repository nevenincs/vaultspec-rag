import { useTheme } from "@carbon/react";
import { Fragment, useState } from "react";
import {
  Button,
  DataTable,
  InlineNotification,
  Modal,
  Search,
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
  TextInput,
} from "@carbon/react";
import { MeterChart } from "@carbon/charts-react";
import { object, reading, request, text, type RecordValue } from "./model";
import { usePolling } from "./use-polling";
import { DataTree } from "./DataTree";
import { Evidence } from "./Logs";
import { bytes } from "./Health";

export function InventoryPage({
  kind,
  paused,
  refresh,
  onRefresh,
}: {
  kind: "repositories" | "storage";
  paused: boolean;
  refresh: number;
  onRefresh: () => void;
}) {
  const { theme } = useTheme();
  const storage = kind === "storage";
  const [filter, setFilter] = useState("");
  const [enroll, setEnroll] = useState(false);
  const [root, setRoot] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<{
    failed: boolean;
    message: string;
  }>();
  const observation = usePolling(
    storage ? "/storage/survey?limit=200" : "/repositories?limit=200",
    object,
    !paused,
    refresh,
    10000,
    35000,
  );
  const raw = observation.data?.[storage ? "namespaces" : "repositories"];
  const records = Array.isArray(raw) ? raw.map(object) : [];
  const filtered = records.filter((row) =>
    [row.root, row.prefix, row.repository_root].some((value) =>
      text(value, "").toLowerCase().includes(filter.toLowerCase()),
    ),
  );
  const headers = storage
    ? [
        { key: "root", header: "Repository / namespace" },
        { key: "status", header: "Classification" },
        { key: "size", header: "Disk footprint" },
        { key: "points", header: "Points" },
      ]
    : [
        { key: "root", header: "Repository / worktree" },
        { key: "status", header: "Status" },
        { key: "watching", header: "Watcher" },
        { key: "resident", header: "Resident seats" },
      ];
  const rows = filtered.map((row) => ({
    id: text(row.prefix),
    root: text(row.root, text(row.prefix)),
    status: storage
      ? text(row.status)
      : row.enrolled === true
        ? "Added"
        : "Discovered worktree",
    size: typeof row.footprint_bytes === "number" ? row.footprint_bytes : -1,
    points: typeof row.points === "number" ? row.points : -1,
    watching:
      row.watching === null
        ? "Service offline"
        : row.watching === true
          ? "Watching"
          : "Inactive",
    resident: row.resident
      ? `${reading(object(row.resident).ref_count)} active references`
      : observation.data?.live_available === false
        ? "Service offline"
        : "Not resident",
  }));
  const act = async (path: string, body?: RecordValue) => {
    if (pending) return;
    setPending(true);
    setFeedback(undefined);
    try {
      const result = await request(
        path,
        body ? { method: "POST", body: JSON.stringify(body) } : {},
        35000,
      );
      if (
        path === "/projects/evict" &&
        result.evicted !== true &&
        result.reason !== "not_found"
      )
        throw new Error(
          text(result.reason, "The resident seat could not be released."),
        );
      setFeedback({
        failed: false,
        message: text(
          result.message,
          text(result.status, text(result.reason, "Operation completed.")),
        ),
      });
      setEnroll(false);
      onRefresh();
    } catch (error) {
      setFeedback({
        failed: true,
        message: error instanceof Error ? error.message : "Operation failed.",
      });
    } finally {
      setPending(false);
    }
  };
  const chartData = records
    .filter(
      (row) =>
        typeof row.footprint_bytes === "number" && row.footprint_bytes > 0,
    )
    .map((row) => ({
      group:
        text(
          row.project_name,
          text(
            row.name,
            text(row.root, text(row.repository_root, text(row.prefix))),
          ),
        )
          .replace(/[\\/]+$/, "")
          .split(/[\\/]+/)
          .at(-1) || "Unnamed project",
      value: Number(row.footprint_bytes) / 1024 ** 3,
    }));
  return (
    <Stack gap={5}>
      <Stack orientation="horizontal" gap={4} className="monitor-toolbar">
        <Search
          id={`${kind}-filter`}
          labelText="Filter repository paths"
          placeholder="Filter paths or namespaces"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
        <Button
          kind="primary"
          size="md"
          disabled={pending || paused}
          onClick={() =>
            storage
              ? void act("/storage/survey?limit=200&fresh=true")
              : setEnroll(true)
          }
        >
          {storage ? "Refresh storage" : "Add repository"}
        </Button>
      </Stack>
      <Evidence observation={observation} paused={paused} />
      {observation.data?.live_available === false && (
        <p className="cds--type-label-01 monitor-muted">
          Showing saved repositories and storage on disk. Live usage is
          available when the service is running.
        </p>
      )}
      {feedback && (
        <InlineNotification
          lowContrast
          title={feedback.failed ? "Operation failed" : "Operation completed"}
          kind={feedback.failed ? "error" : "info"}
          subtitle={feedback.message}
          onClose={() => setFeedback(undefined)}
        />
      )}
      {storage && chartData.length > 0 && (
        <MeterChart
          data={chartData}
          options={{
            title: "Storage by repository",
            height: "160px",
            theme,
            toolbar: { enabled: false },
            animations: false,
            meter: {
              proportional: {
                total: chartData.reduce((sum, row) => sum + row.value, 0),
                unit: "GiB",
              },
            },
          }}
        />
      )}
      {!storage && Boolean(observation.data?.seats) && (
        <DataTree
          value={object(observation.data?.seats)}
          label="Service seats"
        />
      )}
      {storage && (
        <DataTree
          value={object(observation.data?.totals)}
          label="Storage overview"
        />
      )}
      <p className="cds--type-label-01 monitor-muted">
        Showing {filtered.length} of {reading(observation.data?.total)}{" "}
        {storage ? "namespaces" : "paths"}
        {observation.data?.truncated === true ? " · Truncated" : ""}
      </p>
      <div className="monitor-table-window">
        <DataTable rows={rows} headers={headers} isSortable size="lg">
          {({ rows, headers, getTableProps, getRowProps, getHeaderProps }) => (
            <Table
              {...getTableProps()}
              aria-label={storage ? "Storage namespaces" : "Repository paths"}
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
                  const record = filtered.find(
                    (item) => item.prefix === row.id,
                  );
                  if (!record) return null;
                  const { key, ...props } = getRowProps({ row });
                  return (
                    <Fragment key={key}>
                      <TableExpandRow
                        {...props}
                        aria-label={`Expand ${text(record.root, row.id)}`}
                      >
                        {row.cells.map((cell) => (
                          <TableCell key={cell.id}>
                            <span className="monitor-value">
                              {cell.info.header === "size"
                                ? bytes(record.footprint_bytes)
                                : cell.info.header === "points"
                                  ? record.points === null
                                    ? "Service offline"
                                    : `${record.points_verified === false ? "≥ " : ""}${reading(record.points)}`
                                  : cell.value}
                            </span>
                          </TableCell>
                        ))}
                      </TableExpandRow>
                      {row.isExpanded && (
                        <TableExpandedRow colSpan={5}>
                          <Stack gap={4} className="monitor-expanded">
                            <DataTree
                              value={record}
                              label={text(record.root, row.id)}
                            />
                            {typeof record.root === "string" &&
                              (storage || record.resident !== null) && (
                                <Button
                                  kind="tertiary"
                                  size="sm"
                                  disabled={
                                    pending ||
                                    paused ||
                                    Boolean(observation.error) ||
                                    (!storage &&
                                      object(record.resident).ref_count !== 0)
                                  }
                                  onClick={() =>
                                    void act("/projects/evict", {
                                      root: record.root,
                                    })
                                  }
                                >
                                  Release resident seat
                                </Button>
                              )}
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
      </div>
      {!records.length && !observation.error && observation.data && (
        <p className="monitor-empty">
          {storage
            ? "No storage namespaces found on disk."
            : "No repositories have been added."}
        </p>
      )}
      <Modal
        open={enroll}
        modalHeading="Add repository"
        primaryButtonText={pending ? "Adding…" : "Add repository"}
        primaryButtonDisabled={pending || !root.trim()}
        secondaryButtonText="Cancel"
        onRequestClose={() => setEnroll(false)}
        onRequestSubmit={() =>
          void act("/repositories/enroll", { root: root.trim(), watch: true })
        }
      >
        {feedback?.failed && (
          <InlineNotification
            lowContrast
            kind="error"
            title="Could not add repository"
            subtitle={feedback.message}
            hideCloseButton
          />
        )}
        <TextInput
          id="repository-root"
          labelText="Repository path on the service machine"
          helperText="Use an existing absolute repository or worktree path."
          value={root}
          onChange={(event) => setRoot(event.target.value)}
        />
      </Modal>
    </Stack>
  );
}
