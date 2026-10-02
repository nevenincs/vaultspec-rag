import { useRef, useState } from "react";
import {
  Button,
  Grid,
  Column,
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
      <Grid narrow className="monitor-grid monitor-control-grid">
        <Column sm={2} md={2} lg={4}>
          <Button
            size="lg"
            kind="primary"
            disabled={
              Boolean(pending) || (!stopped && Boolean(health) && !stale)
            }
            onClick={() => void send("start")}
          >
            Start service
          </Button>
        </Column>
        <Column sm={2} md={2} lg={4}>
          <Button
            size="lg"
            kind="tertiary"
            disabled={
              Boolean(pending) ||
              !health ||
              stopped ||
              stale ||
              mode === "quiesced" ||
              mode === "paused"
            }
            onClick={() => void send("pause")}
          >
            Pause service
          </Button>
        </Column>
        <Column sm={2} md={2} lg={4}>
          <Button
            size="lg"
            kind="tertiary"
            disabled={
              Boolean(pending) ||
              !health ||
              stopped ||
              stale ||
              ![
                "quiesced",
                "paused",
                "pausing",
                "draining",
                "warming",
              ].includes(mode)
            }
            onClick={() => void send("resume")}
          >
            Resume service
          </Button>
        </Column>
        <Column sm={2} md={2} lg={4}>
          <Button
            size="lg"
            kind="danger--tertiary"
            disabled={Boolean(pending) || !health || stopped || stale}
            onClick={() => setConfirm(true)}
          >
            Stop service
          </Button>
        </Column>
      </Grid>
      {pending && (
        <InlineLoading description={`${pending} service requested…`} />
      )}
      {feedback && (
        <InlineNotification
          lowContrast
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
