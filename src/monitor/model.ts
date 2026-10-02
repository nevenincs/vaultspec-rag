export type RecordValue = Record<string, unknown>;
export type Work = { kind: "job" | "request"; id: string };
export type Jobs = {
  records: RecordValue[];
  summary: RecordValue;
  total: number | null;
  matched: number | null;
};
export type Activity = {
  records: RecordValue[];
  counts: RecordValue;
  returned: number;
  matched: number | null;
};
export type LogGroup = {
  source: string;
  lines: string[];
  marker: string;
  truncated: boolean;
  truncation: RecordValue;
  matched: number;
};
export type LogOptions = {
  source: string;
  lines: number;
  offset: number;
  contains: string;
  order: string;
};
const defaultLogOptions: LogOptions = {
  source: "all",
  lines: 200,
  offset: 0,
  contains: "",
  order: "asc",
};

export function object(value: unknown): RecordValue {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as RecordValue)
    : {};
}

/** Compare source values before adding units or localized number formatting. */
export function compareValues(left: unknown, right: unknown): number {
  if (left === null || left === undefined)
    return right === null || right === undefined ? 0 : 1;
  if (right === null || right === undefined) return -1;
  const numeric = (value: unknown) =>
    typeof value === "number"
      ? value
      : typeof value === "string" &&
          /^[-+]?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(value.trim())
        ? Number(value)
        : NaN;
  const a = numeric(left),
    b = numeric(right);
  return Number.isFinite(a) && Number.isFinite(b)
    ? a - b
    : String(left).localeCompare(String(right), undefined, {
        numeric: true,
        sensitivity: "base",
      });
}

export function text(value: unknown, fallback = "Not reported"): string {
  return typeof value === "string" && value ? value : fallback;
}

export function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

export function count(value: unknown): number | null {
  const result = number(value);
  return result !== null && Number.isInteger(result) ? result : null;
}

export function reading(value: unknown, unit = ""): string {
  const result = number(value);
  return result === null
    ? "—"
    : `${Number(result.toFixed(3)).toLocaleString()}${unit}`;
}

export function clock(value: unknown): string {
  const numeric = number(value);
  const date =
    numeric !== null ? new Date(numeric * 1000) : new Date(text(value, ""));
  return Number.isNaN(date.getTime()) ? "Not reported" : date.toLocaleString();
}

export async function request(
  path: string,
  options: RequestInit = {},
  timeout = 7000,
): Promise<RecordValue> {
  const signal = options.signal
    ? AbortSignal.any([options.signal, AbortSignal.timeout(timeout)])
    : AbortSignal.timeout(timeout);
  const response = await fetch(`/api/monitor${path}`, {
    ...options,
    signal,
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  const raw: unknown = await response.json();
  const payload = object(raw);
  if (!response.ok || (payload.ok === false && path !== "/lifecycle")) {
    throw new Error(
      text(
        payload.message,
        text(payload.error, `Service response ${response.status}`),
      ).slice(0, 2048),
    );
  }
  if (Object.keys(payload).length === 0)
    throw new Error("The service returned data that could not be displayed.");
  return payload;
}

export function health(payload: RecordValue): RecordValue {
  if (typeof payload.status !== "string" || !payload.status) {
    throw new Error("The service did not report its health.");
  }
  return payload;
}

function records(raw: unknown, identity: string): RecordValue[] {
  if (!Array.isArray(raw) || raw.length > 100)
    throw new Error("Invalid bounded work list.");
  const result = raw.map(object);
  const ids = result.map((record) => text(record[identity], ""));
  if (ids.some((id) => !id) || new Set(ids).size !== ids.length) {
    throw new Error("Invalid work identities.");
  }
  return result;
}

export function jobs(payload: RecordValue): Jobs {
  return {
    records: records(payload.jobs, "id"),
    summary: object(payload.summary),
    total: count(payload.total),
    matched: count(payload.matched ?? payload.total),
  };
}

export function activity(payload: RecordValue): Activity {
  const rows: RecordValue[] = [];
  for (const [lane, state] of [
    ["queued", "queued"],
    ["active", "active"],
    ["recent", "terminal"],
  ]) {
    for (const record of records(
      payload[lane] ?? (lane === "queued" ? [] : undefined),
      "request_id",
    )) {
      const disclosed = typeof record.query === "string";
      const redacted = record.query_redacted === true;
      if (record.state !== state || disclosed === redacted)
        throw new Error(
          "The service returned query data that could not be displayed.",
        );
      rows.push(record);
    }
  }
  if (
    rows.length > 100 ||
    new Set(rows.map((record) => record.request_id)).size !== rows.length
  ) {
    throw new Error("Invalid serving identities.");
  }
  const returned = count(payload.returned);
  const counts = object(payload.all_counts ?? payload.counts);
  if (
    returned !== rows.length ||
    ["active", "recent", "total"].some((key) => count(counts[key]) === null)
  ) {
    throw new Error("Invalid serving summary.");
  }
  if (payload.all_counts !== undefined && count(counts.queued) === null)
    throw new Error("Invalid serving queue summary.");
  return {
    records: Array.isArray(payload.records)
      ? records(payload.records, "request_id")
      : rows,
    counts: { ...counts, queued: counts.queued ?? payload.queued_count },
    returned,
    matched: count(payload.matched ?? counts.total),
  };
}

export function logPath(
  work?: Work,
  options: LogOptions = defaultLogOptions,
): string {
  const filters = new URLSearchParams({
    source: work ? "service" : options.source,
    lines: String(options.lines),
    offset: String(options.offset),
    order: options.order,
  });
  if (work) filters.set(work.kind === "job" ? "job_id" : "request_id", work.id);
  if (options.contains) filters.set("contains", options.contains);
  return `/logs/json?${filters}`;
}

export function logs(
  payload: RecordValue,
  work?: Work,
  options: LogOptions = defaultLogOptions,
): LogGroup[] {
  const source = work ? "service" : options.source;
  const sources = source === "all" ? ["service", "qdrant"] : [source];
  const filters: Record<string, string> = work
    ? { [work.kind === "job" ? "job_id" : "request_id"]: work.id }
    : {};
  if (options.contains) filters.contains = options.contains;
  const actual = object(payload.filters);
  if (
    payload.source !== source ||
    payload.limit !== options.lines ||
    (payload.offset ?? 0) !== options.offset ||
    (payload.order ?? "asc") !== options.order ||
    Object.keys(actual).length !== Object.keys(filters).length ||
    Object.entries(filters).some(([key, value]) => actual[key] !== value) ||
    !Array.isArray(payload.groups) ||
    payload.groups.length !== sources.length
  ) {
    throw new Error("The service returned logs for a different scope.");
  }
  return payload.groups.map((raw, index) => {
    const group = object(raw);
    const encoder = new TextEncoder();
    if (
      group.source !== sources[index] ||
      !Array.isArray(group.lines) ||
      group.lines.length > options.lines ||
      group.lines.some((line) => typeof line !== "string")
    ) {
      throw new Error("The service returned an invalid log window.");
    }
    const lines = group.lines as string[];
    const marker = text(group.marker, "");
    const truncation = object(group.truncation);
    const cost = (line: string) =>
      encoder.encode(JSON.stringify(line)).length + 1;
    const contentBytes =
      lines.reduce((total, line) => total + cost(line), 0) +
      (marker ? cost(marker) : 0);
    const metadata = [group.truncated, group.marker, group.truncation].some(
      (value) => value !== undefined && value !== null,
    );
    if (
      lines.some((line) => encoder.encode(line).length > 65536) ||
      contentBytes > 2097152 ||
      (metadata &&
        (group.truncated !== true ||
          marker !==
            "[vaultspec-rag: managed log output truncated by byte budget]" ||
          [
            "record_limit_bytes",
            "source_limit_bytes",
            "scanned_bytes",
            "returned_content_bytes",
            "omitted_bytes_at_least",
            "record_truncations",
            "omitted_response_records",
          ].some((key) => count(truncation[key]) === null) ||
          truncation.record_limit_bytes !== 65536 ||
          truncation.source_limit_bytes !== 2097152 ||
          Number(truncation.scanned_bytes) > 2097152 ||
          truncation.returned_content_bytes !== contentBytes ||
          typeof truncation.source_budget_exhausted !== "boolean" ||
          typeof truncation.response_budget_exhausted !== "boolean"))
    )
      throw new Error(
        "The service returned invalid log bounds or truncation evidence.",
      );
    return {
      source: sources[index],
      lines,
      marker,
      truncated: group.truncated === true,
      truncation,
      matched: count(group.matched) ?? lines.length,
    };
  });
}

export function safeLog(line: string): string {
  // Neutralize ANSI escapes and terminal control bytes; React escapes markup.
  return (
    line
      // eslint-disable-next-line no-control-regex -- Sanitizing terminal controls is intentional.
      .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "")
      // eslint-disable-next-line no-control-regex -- Keep control bytes inert in raw log records.
      .replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "�")
  );
}

export function jobProgress(job: RecordValue): string {
  const progress = object(job.progress);
  const completed = count(progress.completed ?? progress.done);
  const total = count(progress.total);
  return (
    [
      text(progress.step ?? job.phase, ""),
      completed === null
        ? ""
        : `${completed.toLocaleString()} / ${total === null ? "—" : total.toLocaleString()}`,
    ]
      .filter(Boolean)
      .join(" · ") || "Not reported"
  );
}

export function rootOf(job: RecordValue): string {
  return text(
    job.project_root ??
      object(job.spec).project_root ??
      object(job.spec).root ??
      object(job.initiator).project_root,
  );
}

export function initiator(job: RecordValue): string {
  const origin = object(job.initiator);
  return (
    [text(origin.kind, ""), text(origin.command, ""), text(origin.user, "")]
      .filter(Boolean)
      .join(" · ") || text(job.trigger)
  );
}
