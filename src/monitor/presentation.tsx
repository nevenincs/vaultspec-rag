import type { ComponentProps, ReactNode } from "react";
import {
  Table,
  DataTable,
  TableBody,
  TableHead,
  TableHeader,
  TableCell,
  TableRow,
  Stack,
  preview__IconIndicator as IconIndicator,
} from "@carbon/react";
import { count, reading, type RecordValue } from "./model";
type StatusKind = ComponentProps<typeof IconIndicator>["kind"];
function statusKind(state: string): StatusKind {
  if (["ready", "active", "succeeded", "healthy"].includes(state))
    return "succeeded";
  if (["failed", "error", "rejected", "interrupted"].includes(state))
    return "failed";
  if (["degraded", "cooldown", "stalled"].includes(state))
    return "caution-major";
  if (
    [
      "running",
      "pausing",
      "draining",
      "warming",
      "cancelling",
      "starting",
    ].includes(state)
  )
    return "in-progress";
  if (["queued", "pending"].includes(state)) return "pending";
  if (["paused", "quiesced", "stopped", "cancelled", "off"].includes(state))
    return "incomplete";
  return "unknown";
}

export function Status({ state, label }: { state: string; label?: string }) {
  return (
    <IconIndicator
      kind={statusKind(state)}
      label={label ?? state.replaceAll("_", " ")}
    />
  );
}

export function Details({ items }: { items: [string, ReactNode][] }) {
  return (
    <DataTable
      rows={items.map(([label]) => ({ id: label, property: label }))}
      headers={[
        { key: "property", header: "Property" },
        { key: "value", header: "Value" },
      ]}
      size="sm"
    >
      {({ getTableProps }) => (
        <Table
          {...getTableProps()}
          aria-label="Service properties"
          className="monitor-details"
        >
          <TableHead>
            <TableRow>
              <TableHeader>Property</TableHeader>
              <TableHeader>Value</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {items.map(([label, value]) => (
              <TableRow key={label}>
                <TableCell>{label}</TableCell>
                <TableCell>{value}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </DataTable>
  );
}

export function Metrics({
  counts,
  labels,
}: {
  counts: RecordValue;
  labels: [string, string][];
}) {
  return (
    <Stack orientation="horizontal" gap={7} className="monitor-metrics">
      {labels.map(([key, label]) => (
        <div key={key}>
          <p className="cds--type-label-01 monitor-muted">{label}</p>
          <p className="cds--type-heading-03">
            {count(counts[key]) === null ? "—" : reading(counts[key])}
          </p>
        </div>
      ))}
    </Stack>
  );
}
