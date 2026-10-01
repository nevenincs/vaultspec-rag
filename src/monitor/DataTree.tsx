import { Fragment, useId, useState } from "react";
import {
  Column,
  DataTable,
  Grid,
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
  TreeNode,
  TreeView,
} from "@carbon/react";
import { diagnostic, object } from "./model";

function scalar(value: unknown): string {
  if (value === null) return "Not reported";
  if (value === undefined) return "Not reported";
  if (typeof value === "object")
    return Array.isArray(value)
      ? `${value.length} records`
      : `${Object.keys(object(value)).length} fields`;
  return String(value);
}

function ValueTable({ value, label }: { value: unknown; label: string }) {
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item] as const)
    : Object.entries(object(value));
  const tabular =
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((item) => Object.keys(object(item)).length > 0);
  const columns = tabular
    ? [...new Set(value.flatMap((item) => Object.keys(object(item))))].slice(
        0,
        8,
      )
    : [];
  const headers = tabular
    ? columns.map((key, index) => ({
        key: `column${index}`,
        header: key.replaceAll("_", " "),
      }))
    : [
        { key: "field", header: Array.isArray(value) ? "Record" : "Field" },
        { key: "value", header: "Value" },
      ];
  const rows = entries.map(([key, item]) => ({
    id: key,
    field: key.replaceAll("_", " "),
    value: typeof item === "number" ? diagnostic(key, item) : scalar(item),
    ...Object.fromEntries(
      columns.map((column, index) => [
        `column${index}`,
        typeof object(item)[column] === "number"
          ? diagnostic(column, object(item)[column])
          : scalar(object(item)[column]),
      ]),
    ),
  }));
  if (!entries.length)
    return (
      <p className="monitor-empty">
        {typeof value === "object" ? "No records reported." : scalar(value)}
      </p>
    );
  return (
    <DataTable rows={rows} headers={headers} size="sm">
      {({ rows, headers, getTableProps, getRowProps, getHeaderProps }) => (
        <Table {...getTableProps()} aria-label={label}>
          <TableHead>
            <TableRow>
              <TableExpandHeader />
              <>
                {headers.map((header) => {
                  const { key, ...props } = getHeaderProps({ header });
                  return (
                    <TableHeader key={key} {...props}>
                      {header.header}
                    </TableHeader>
                  );
                })}
              </>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => {
              const item = entries.find(([key]) => key === row.id)?.[1];
              const nested = item !== null && typeof item === "object";
              const { key, ...props } = getRowProps({ row });
              return (
                <Fragment key={key}>
                  {nested ? (
                    <TableExpandRow {...props} aria-label={`Expand ${row.id}`}>
                      {row.cells.map((cell) => (
                        <TableCell key={cell.id}>
                          <span className="monitor-value">{cell.value}</span>
                        </TableCell>
                      ))}
                    </TableExpandRow>
                  ) : (
                    <TableRow>
                      <TableCell />
                      {row.cells.map((cell) => (
                        <TableCell key={cell.id}>
                          <span className="monitor-value">{cell.value}</span>
                        </TableCell>
                      ))}
                    </TableRow>
                  )}
                  {row.isExpanded && nested && (
                    <TableExpandedRow colSpan={headers.length + 1}>
                      <ValueTable value={item} label={`${label} / ${row.id}`} />
                    </TableExpandedRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}
    </DataTable>
  );
}

/** A structural tree and its nested table share the same parent record. */
export function DataTree({
  value,
  label,
  initialPath = [],
}: {
  value: unknown;
  label: string;
  initialPath?: string[];
}) {
  const id = useId();
  const [path, setPath] = useState<string[]>(initialPath);
  let selected: unknown = value;
  for (const part of path)
    selected = Array.isArray(selected)
      ? selected[Number(part)]
      : object(selected)[part];
  const nodes = (item: unknown, trail: string[], depth: number) => {
    if (depth > 5 || item === null || typeof item !== "object") return null;
    return Object.entries(item)
      .filter(([, child]) => child !== null && typeof child === "object")
      .slice(0, 100)
      .map(([key, child]) => {
        const next = [...trail, key];
        return (
          <TreeNode
            key={key}
            id={`${id}-${JSON.stringify(next)}`}
            label={`${key.replaceAll("_", " ")}${Array.isArray(child) ? ` (${child.length})` : ""}`}
            onSelect={() => setPath(next)}
          >
            {nodes(child, next, depth + 1)}
          </TreeNode>
        );
      });
  };
  return (
    <Grid narrow className="monitor-grid monitor-relation">
      <Column sm={4} md={3} lg={4}>
        <TreeView
          label={label}
          size="sm"
          active={`${id}-${JSON.stringify(path)}`}
        >
          <TreeNode
            id={`${id}-[]`}
            label={label}
            isExpanded
            onSelect={() => setPath([])}
          >
            {nodes(value, [], 0)}
          </TreeNode>
        </TreeView>
      </Column>
      <Column sm={4} md={5} lg={12}>
        <Stack gap={3}>
          <p className="cds--type-label-01 monitor-muted">
            {[label, ...path].join(" / ")}
          </p>
          <div className="monitor-table-window">
            <ValueTable value={selected} label={[label, ...path].join(" / ")} />
          </div>
        </Stack>
      </Column>
    </Grid>
  );
}
