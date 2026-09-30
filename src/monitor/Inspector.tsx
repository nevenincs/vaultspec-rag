import { useEffect, useRef, useState } from "react";
import {
  Button,
  Column,
  Grid,
  InlineNotification,
  Modal,
  Stack,
  Tile,
} from "@carbon/react";
import {
  clock,
  count,
  diagnostic,
  initiator,
  jobProgress,
  object,
  reading,
  request,
  rootOf,
  text,
  type RecordValue,
  type Work,
} from "./model";
import { Details, Status } from "./presentation";
import { Evidence, Logs } from "./Logs";
import type { Observation } from "./use-polling";
function JobControls({
  job,
  disabled,
  onRefresh,
}: {
  job: RecordValue;
  disabled: boolean;
  onRefresh: () => void;
}) {
  const capabilities = object(job.capabilities);
  const revision = count(job.revision);
  const id = text(job.id, " ");
  const [pending, setPending] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [feedback, setFeedback] = useState<{
    message: string;
    failed: boolean;
  }>();
  const control = useRef<AbortController | null>(null);
  useEffect(() => () => control.current?.abort(), []);
  const send = async (action: string) => {
    if (pending || disabled) return;
    const flag = {
      pause: "pausable",
      resume: "resumable",
      stop: "cancellable",
      retry: "retryable",
      delete: "deletable",
    }[action];
    if (
      !flag ||
      capabilities[flag] !== true ||
      (["pause", "resume", "stop"].includes(action) &&
        (!revision || revision < 1))
    )
      return;
    setConfirm(false);
    setPending(true);
    setFeedback(undefined);
    const controller = new AbortController();
    control.current = controller;
    try {
      const states: Record<string, string> = {
        pause: "paused",
        resume: "running",
        stop: "cancelled",
      };
      const result = await request(
        `/jobs/${encodeURIComponent(id)}${action === "retry" ? "/retry" : states[action] ? "/desired-state" : ""}`,
        {
          method:
            action === "delete"
              ? "DELETE"
              : action === "retry"
                ? "POST"
                : "PUT",
          signal: controller.signal,
          body:
            action === "delete"
              ? undefined
              : JSON.stringify(
                  action === "retry"
                    ? {
                        initiator: {
                          kind: "cli",
                          command: "monitor_job_retry",
                        },
                      }
                    : {
                        state: states[action],
                        mode: "graceful",
                        expected_revision: revision,
                      },
                ),
        },
      );
      if (!controller.signal.aborted)
        setFeedback({
          failed: false,
          message: text(
            result.message,
            `${action} request accepted. Waiting for the service observation.`,
          ),
        });
    } catch (error) {
      if (!controller.signal.aborted)
        setFeedback({
          failed: true,
          message:
            error instanceof Error
              ? error.message
              : "The service refused this job action.",
        });
    } finally {
      if (!controller.signal.aborted) {
        setPending(false);
        onRefresh();
      }
    }
  };
  return (
    <Stack gap={4}>
      <Stack orientation="horizontal" gap={3} className="monitor-controls">
        {[
          ["pause", "Pause", "pausable"],
          ["resume", "Resume", "resumable"],
          ["stop", "Stop", "cancellable"],
          ["retry", "Retry", "retryable"],
          ["delete", "Delete record", "deletable"],
        ].map(([action, label, flag]) => (
          <Button
            key={action}
            size="sm"
            kind={action === "delete" ? "danger--tertiary" : "tertiary"}
            disabled={
              disabled ||
              pending ||
              capabilities[flag] !== true ||
              (["pause", "resume", "stop"].includes(action) &&
                (!revision || revision < 1))
            }
            onClick={() =>
              action === "delete" ? setConfirm(true) : void send(action)
            }
          >
            {label}
          </Button>
        ))}
      </Stack>
      <p className="cds--type-label-01 monitor-muted">
        {pending
          ? "Sending job request…"
          : "Controls follow service capabilities. Requested state is shown separately from observed state."}
      </p>
      {feedback && (
        <InlineNotification
          kind={feedback.failed ? "error" : "info"}
          title={
            feedback.failed ? "Job action refused" : "Job request received"
          }
          subtitle={feedback.message}
          hideCloseButton
          role="status"
        />
      )}
      <Modal
        open={confirm}
        danger
        modalHeading="Delete this job record?"
        primaryButtonText="Delete record"
        secondaryButtonText="Cancel"
        dangerDescription="Deletes the selected finished job record"
        primaryButtonDisabled={
          disabled || pending || capabilities.deletable !== true
        }
        onRequestClose={() => setConfirm(false)}
        onRequestSubmit={() => void send("delete")}
      >
        <p className="cds--type-body-01">
          This removes job {id} from the retained job history.
        </p>
      </Modal>
    </Stack>
  );
}

export function Inspector({
  work,
  record,
  paused,
  refresh,
  stale,
  observation,
  onRefresh,
  onClose,
}: {
  work: Work;
  record: RecordValue;
  paused: boolean;
  refresh: number;
  stale: boolean;
  observation: Observation<unknown>;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const indexing = work.kind === "job";
  const timings = object(record.timings);
  const waits = Array.isArray(record.waits) ? record.waits : [];
  const degradation = object(record.degradation);
  return (
    <section aria-labelledby="inspector-heading" id="work-inspector">
      <Stack gap={5}>
        <Stack orientation="horizontal" gap={5} className="monitor-toolbar">
          <h2
            id="inspector-heading"
            tabIndex={-1}
            className="cds--type-heading-03"
          >
            {indexing ? "Indexing job" : "Serving request"}
          </h2>
          <Button size="sm" kind="ghost" onClick={onClose}>
            Close inspector
          </Button>
        </Stack>
        <p className="cds--type-code-01 monitor-identity">{work.id}</p>
        <Evidence observation={observation} paused={paused} />
        <Grid narrow withRowGap className="monitor-grid">
          <Column sm={4} md={8} lg={indexing ? 16 : 8}>
            <Tile>
              <Stack gap={5}>
                <Details
                  items={
                    indexing
                      ? [
                          [
                            "Observed state",
                            <Status state={text(record.state, "unknown")} />,
                          ],
                          ["Requested state", text(record.desired_state)],
                          ["Project", rootOf(record)],
                          ["Initiator", initiator(record)],
                          ["Progress", jobProgress(record)],
                          [
                            "Last progress age",
                            reading(record.last_progress_age_seconds, " s"),
                          ],
                          ["Runtime", reading(record.runtime_seconds, " s")],
                          ["Revision", reading(record.revision)],
                          ["Started", clock(record.started_at)],
                          ["Finished", clock(record.finished_at)],
                          ["Result", text(record.result)],
                          ["Error", text(record.error_kind ?? record.error)],
                          [
                            "Job health",
                            record.degradation === null
                              ? "Healthy"
                              : text(degradation.reason ?? degradation.verdict),
                          ],
                          [
                            "Health detail",
                            text(degradation.detail ?? degradation.message),
                          ],
                        ]
                      : [
                          [
                            "State",
                            <Status
                              state={text(
                                record.outcome,
                                text(record.state, "unknown"),
                              )}
                              label={text(record.state)}
                            />,
                          ],
                          [
                            "Query",
                            text(
                              record.query,
                              record.query_redacted === true
                                ? "Redacted by service"
                                : "Not reported",
                            ),
                          ],
                          ["Source", text(record.source)],
                          ["Root", text(record.root)],
                          ["Started", clock(record.started_at)],
                          ["Finished", clock(record.finished_at)],
                          ["Duration", reading(record.total_seconds, " s")],
                          ["HTTP status", reading(record.status_code)],
                          ["Results", reading(record.result_count)],
                          ["Availability", text(record.availability_cause)],
                          [
                            "Error",
                            text(record.error_message ?? record.error_code),
                          ],
                        ]
                  }
                />
                {indexing && (
                  <JobControls
                    key={work.id}
                    job={record}
                    disabled={paused || stale}
                    onRefresh={onRefresh}
                  />
                )}
              </Stack>
            </Tile>
          </Column>
          {!indexing && (
            <Column sm={4} md={8} lg={8}>
              <Tile>
                <Stack gap={5}>
                  <h3 className="cds--type-heading-compact-02">
                    Request diagnostics
                  </h3>
                  {Object.keys(timings).length ? (
                    <Details
                      items={Object.entries(timings).map(([name, value]) => [
                        name,
                        diagnostic(name, value),
                      ])}
                    />
                  ) : (
                    <p className="cds--type-body-01 monitor-muted">
                      No timings reported yet.
                    </p>
                  )}
                  {waits.map((raw, index) => {
                    const wait = object(raw);
                    return (
                      <Details
                        key={index}
                        items={[
                          ["Wait cause", text(wait.cause)],
                          ["Waited", reading(wait.waited_seconds, " s")],
                          [
                            "Configured bound",
                            reading(wait.configured_bound_seconds, " s"),
                          ],
                          [
                            "Remaining bound",
                            reading(wait.remaining_bound_seconds, " s"),
                          ],
                        ]}
                      />
                    );
                  })}
                </Stack>
              </Tile>
            </Column>
          )}
        </Grid>
        <Logs work={work} paused={paused} refresh={refresh} />
      </Stack>
    </section>
  );
}
