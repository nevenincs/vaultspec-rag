import { Fragment, useId, useState } from "react";
import {
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
import { compareValues, object } from "./model";

function display(value: unknown): string {
  if (value === null || value === undefined) return "Not reported";
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === "object") return `${Object.keys(value).length} fields`;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/** One inline hierarchy; expansion belongs to the field path, not a poll result. */
export function DataTree({ value, label }: { value: unknown; label: string }) {
  const id = useId();
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [sorting, setSorting] = useState<
    Record<string, { key: string; direction: "ASC" | "DESC" }>
  >({});
  const toggle = (key: string) =>
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const table = (data: unknown, path: string[], title: string) => {
    if (data === null || typeof data !== "object")
      return <p className="monitor-value">{display(data)}</p>;
    const entries = Object.entries(data);
    if (!entries.length) return <p className="monitor-muted">No items.</p>;
    const records =
      Array.isArray(data) &&
      data.every(
        (item) =>
          item !== null && typeof item === "object" && !Array.isArray(item),
      );
    const columns = records
      ? [...new Set(data.flatMap((item) => Object.keys(object(item))))]
          .filter((key) =>
            data.some(
              (item) =>
                object(item)[key] !== null &&
                typeof object(item)[key] !== "object",
            ),
          )
          .slice(0, 8)
      : [];
    const needsDetails = (item: unknown) =>
      item !== null &&
      typeof item === "object" &&
      (!columns.length ||
        Object.keys(item).some((key) => !columns.includes(key)) ||
        Object.values(item).some(
          (value) => value !== null && typeof value === "object",
        ));
    const hasChildren = entries.some(([, item]) => needsDetails(item));
    const headers = columns.length
      ? columns
      : [Array.isArray(data) ? "Item" : "Field", "Value"];
    const tableKey = JSON.stringify(path);
    const sort = sorting[tableKey];
    const ordered = sort
      ? [...entries].sort(([a, left], [b, right]) => {
          const av = columns.length
            ? object(left)[sort.key]
            : sort.key === "Value"
              ? left
              : a;
          const bv = columns.length
            ? object(right)[sort.key]
            : sort.key === "Value"
              ? right
              : b;
          return compareValues(av, bv) * (sort.direction === "ASC" ? 1 : -1);
        })
      : entries;
    return (
      <Table size="sm" aria-label={title} className="monitor-nested-table">
        <TableHead>
          <TableRow>
            {hasChildren && <TableExpandHeader />}
            {headers.map((key) => (
              <TableHeader
                key={key}
                isSortable
                isSortHeader={sort?.key === key}
                sortDirection={sort?.key === key ? sort.direction : "NONE"}
                onClick={() =>
                  setSorting((previous) => ({
                    ...previous,
                    [tableKey]: {
                      key,
                      direction:
                        sort?.key === key && sort.direction === "ASC"
                          ? "DESC"
                          : "ASC",
                    },
                  }))
                }
              >
                {key.replaceAll("_", " ")}
              </TableHeader>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {ordered.map(([key, item]) => {
            const identity = JSON.stringify([...path, key]);
            const open = expanded.has(identity);
            const nested = needsDetails(item);
            const rowLabel = Array.isArray(data)
              ? String(Number(key) + 1)
              : key.replaceAll("_", " ");
            const cells = columns.length ? (
              columns.map((column) => (
                <TableCell key={column}>
                  <span className="monitor-value">
                    {display(object(item)[column])}
                  </span>
                </TableCell>
              ))
            ) : (
              <>
                <TableCell>{rowLabel}</TableCell>
                <TableCell>
                  <span className="monitor-value">{display(item)}</span>
                </TableCell>
              </>
            );
            return (
              <Fragment key={identity}>
                {nested ? (
                  <TableExpandRow
                    isExpanded={open}
                    onExpand={() => toggle(identity)}
                    aria-label={`Expand ${rowLabel}`}
                    aria-controls={`${id}-${encodeURIComponent(identity)}`}
                    expandIconDescription={
                      open ? "Collapse details" : "Expand details"
                    }
                  >
                    {cells}
                  </TableExpandRow>
                ) : (
                  <TableRow>
                    {hasChildren && <TableCell />}
                    {cells}
                  </TableRow>
                )}
                {nested && open && (
                  <TableExpandedRow
                    id={`${id}-${encodeURIComponent(identity)}`}
                    colSpan={headers.length + Number(hasChildren)}
                    className="monitor-nested-expansion"
                  >
                    {table(item, [...path, key], `${title} / ${rowLabel}`)}
                  </TableExpandedRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    );
  };
  return (
    <div className="monitor-table-window monitor-data-details">
      {table(value, [], label)}
    </div>
  );
}
