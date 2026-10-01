import { useEffect, useRef, useState } from "react";
import { Button, InlineNotification, Modal, Stack } from "@carbon/react";
import { count, object, request, text, type RecordValue } from "./model";
export function JobControls({
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
