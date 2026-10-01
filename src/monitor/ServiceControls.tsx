import { useRef, useState } from "react";
import {
  Button,
  InlineLoading,
  InlineNotification,
  Modal,
  Stack,
} from "@carbon/react";
import { object, request, text, type RecordValue } from "./model";

export function ServiceControls({
  health,
  state,
  lifecycle,
  stale,
  onRefresh,
}: {
  health?: RecordValue;
  state?: RecordValue;
  lifecycle?: RecordValue;
  stale: boolean;
  onRefresh: () => void;
}) {
  const [pending, setPending] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [feedback, setFeedback] = useState<{
    failed: boolean;
    message: string;
  }>();
  const busy = useRef(false);
  const quiesce = object(state?.quiesce);
  const mode = text(quiesce.state, text(health?.status, "unknown"));
  const stopped = lifecycle?.state === "stopped" && (!health || stale);
  const send = async (action: string) => {
    if (busy.current) return;
    busy.current = true;
    setConfirm(false);
    setPending(action);
    setFeedback(undefined);
    try {
      const result = await request(
        ["start", "stop"].includes(action)
          ? `/lifecycle/${action}`
          : `/${action}`,
        { method: "POST", body: "{}" },
        action === "start" ? 905000 : 125000,
      );
      setFeedback({
        failed: false,
        message: text(
          result.message,
          text(
            result.status,
            text(object(result.data).status, "Service action completed."),
          ),
        ),
      });
    } catch (error) {
      setFeedback({
        failed: true,
        message:
          error instanceof Error ? error.message : "Service action failed.",
      });
    } finally {
      busy.current = false;
      setPending("");
      onRefresh();
    }
  };
  return (
    <Stack gap={3}>
      <Stack orientation="horizontal" gap={3} className="monitor-controls">
        <Button
          size="sm"
          kind="primary"
          disabled={Boolean(pending) || (!stopped && Boolean(health) && !stale)}
          onClick={() => void send("start")}
        >
          Start service
        </Button>
        <Button
          size="sm"
          kind="tertiary"
          disabled={
            Boolean(pending) ||
            stopped ||
            stale ||
            mode === "quiesced" ||
            mode === "paused"
          }
          onClick={() => void send("pause")}
        >
          Pause service
        </Button>
        <Button
          size="sm"
          kind="tertiary"
          disabled={
            Boolean(pending) ||
            stopped ||
            stale ||
            !["quiesced", "paused", "pausing", "draining", "warming"].includes(
              mode,
            )
          }
          onClick={() => void send("resume")}
        >
          Resume service
        </Button>
        <Button
          size="sm"
          kind="danger--tertiary"
          disabled={Boolean(pending) || stopped || stale}
          onClick={() => setConfirm(true)}
        >
          Stop service
        </Button>
      </Stack>
      {pending && (
        <InlineLoading description={`${pending} service requested…`} />
      )}
      {feedback && (
        <InlineNotification
          kind={feedback.failed ? "error" : "info"}
          title={feedback.failed ? "Service action failed" : "Service action"}
          subtitle={feedback.message}
          onClose={() => setFeedback(undefined)}
        />
      )}
      <Modal
        open={confirm}
        danger
        modalHeading="Stop the RAG service?"
        primaryButtonText="Stop service"
        secondaryButtonText="Cancel"
        onRequestClose={() => setConfirm(false)}
        onRequestSubmit={() => void send("stop")}
      >
        <p>
          Active work will stop. You can start the service again from this
          monitor.
        </p>
      </Modal>
    </Stack>
  );
}
