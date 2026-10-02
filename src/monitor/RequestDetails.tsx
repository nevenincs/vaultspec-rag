import {
  Accordion,
  AccordionItem,
  Column,
  Grid,
  InlineNotification,
  Stack,
} from "@carbon/react";
import { DataTree } from "./DataTree";
import {
  clock,
  initiator,
  jobProgress,
  object,
  reading,
  rootOf,
  text,
  type RecordValue,
  type Work,
} from "./model";

export function RequestDetails({
  record,
  kind,
}: {
  record: RecordValue;
  kind: Work["kind"];
}) {
  const indexing = kind === "job";
  const spec = object(record.spec);
  const times = object(record.timestamps);
  const response = record.response;
  const resultRows = object(response).results;
  const summary = indexing
    ? [
        ["Repository", rootOf(record)],
        ["Source", text(spec.source ?? record.source)],
        ["Mode", text(spec.mode)],
        ["Requested by", initiator(record)],
        ["Started", clock(times.started_at)],
        ["Finished", times.finished_at ? clock(times.finished_at) : "—"],
      ]
    : [
        ["Repository", text(record.root)],
        ["Source", text(record.source)],
        ["Started", clock(record.started_at)],
        ["Duration", reading(record.total_seconds, " s")],
        ["Results", reading(record.result_count)],
        ["Requested results", reading(record.top_k)],
      ];
  const error = text(
    record.error_message ?? record.error ?? record.error_kind,
    "",
  );
  const excluded = new Set([
    "id",
    "request_id",
    "spec",
    "timestamps",
    "query",
    "response",
    "result",
    "progress",
    "error",
    "error_kind",
    "capabilities",
    "state",
    "outcome",
    "project_root",
    "root",
    "request_inputs",
    "error_message",
    "top_k",
    "source",
    "started_at",
    "total_seconds",
    "result_count",
    "initiator",
  ]);
  const diagnostics = Object.fromEntries(
    Object.entries(record).filter(
      ([key, value]) => !excluded.has(key) && value !== null,
    ),
  );
  const input = indexing
    ? Object.fromEntries(
        Object.entries(spec).filter(
          ([key]) => !["project_root", "source", "mode"].includes(key),
        ),
      )
    : record.request_inputs;
  return (
    <Stack gap={5} className="monitor-request-details">
      <Grid narrow className="monitor-grid monitor-request-summary">
        {summary.map(([label, value]) => (
          <Column key={label} sm={4} md={4} lg={8}>
            <dl>
              <dt className="cds--type-label-01 monitor-muted">{label}</dt>
              <dd className="cds--type-body-01 monitor-value">{value}</dd>
            </dl>
          </Column>
        ))}
      </Grid>
      <p className="cds--type-label-01 monitor-muted monitor-value">
        Request ID: {text(record.id ?? record.request_id)}
      </p>
      {indexing ? (
        <section>
          <h3 className="cds--type-heading-compact-01">Progress</h3>
          <p className="cds--type-body-01">{jobProgress(record)}</p>
        </section>
      ) : (
        <section>
          <h3 className="cds--type-heading-compact-01">Query</h3>
          <p className="cds--type-body-01 monitor-value">
            {text(record.query, "Query text is not available")}
          </p>
        </section>
      )}
      {error && (
        <InlineNotification
          lowContrast
          kind="error"
          title="Request failed"
          subtitle={error}
          hideCloseButton
        />
      )}
      {indexing && record.result !== null && record.result !== undefined && (
        <section>
          <h3 className="cds--type-heading-compact-01">Result</h3>
          {typeof record.result === "string" ? (
            <p className="cds--type-body-01 monitor-value">{record.result}</p>
          ) : (
            <DataTree label="Indexing result" value={record.result} />
          )}
        </section>
      )}
      {!indexing && (
        <section>
          <h3 className="cds--type-heading-compact-01">Results</h3>
          {response !== undefined && response !== null ? (
            <DataTree label="Query results" value={resultRows ?? response} />
          ) : (
            <p className="monitor-muted">
              {record.state === "terminal"
                ? "No returned results were saved for this query."
                : "Results will appear when the query finishes."}
            </p>
          )}
        </section>
      )}
      <Accordion size="sm">
        {input !== undefined && Object.keys(object(input)).length > 0 && (
          <AccordionItem title="Input parameters">
            <DataTree label="Input parameters" value={input} />
          </AccordionItem>
        )}
        <AccordionItem title="Timing and diagnostics">
          <DataTree
            label="Request diagnostics"
            value={{
              ...(Object.keys(times).length ? { timing: times } : {}),
              ...diagnostics,
              ...(!indexing && resultRows !== undefined
                ? {
                    response_details: Object.fromEntries(
                      Object.entries(object(response)).filter(
                        ([key]) => key !== "results",
                      ),
                    ),
                  }
                : {}),
            }}
          />
        </AccordionItem>
      </Accordion>
    </Stack>
  );
}
