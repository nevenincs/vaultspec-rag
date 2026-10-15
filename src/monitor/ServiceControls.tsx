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
import {
  clientMarginMilliseconds,
  lifecycleBudgetMilliseconds,
} from "./lifecycle-budget.ts";
import {
  MonitorUnreachableError,
  object,
  request,
  text,
  type RecordValue,
} from "./model";

function lifecycleBudget(action: string): number {
  // A page cannot read the operator's store readiness window, so the default
  // one stands here; the monitor's own server honours whatever is set.
  const budget = lifecycleBudgetMilliseconds();
  if (action === "restart") return budget.restart;
  if (action === "start") return budget.start;
  // Pause, resume and stop all end in the monitor's stop-shaped budget.
  return budget.stop;
}

const stoppedWithMonitor =
  "The service stopped, and this monitor closed with it. Run `vaultspec-rag server start` to start it again.";

export function ServiceControls({
  health,
  state,
  lifecycle,
  stale,
  unreachable,
  onRefresh,
  onRestartingChange,
}: {
  health?: RecordValue;
  state?: RecordValue;
  lifecycle?: RecordValue;
  stale: boolean;
  unreachable: boolean;
  onRefresh: () => void;
  onRestartingChange: (restarting: boolean) => void;
}) {
  const [pending, setPending] = useState("");
  const [confirm, setConfirm] = useState<"" | "stop" | "restart">("");
  const [feedback, setFeedback] = useState<{
    failed: boolean;
    message: string;
  }>();
  const busy = useRef(false);
  const quiesce = object(state?.quiesce);
  const mode = text(quiesce.state, text(health?.status, "unknown"));
  const borrowed = quiesce.borrower_bound === true;
  // Any lifecycle outcome without a healthy service can be started: a daemon
  // that still runs but stopped answering or heartbeating, and the window a
  // failed restart leaves. A daemon process that died takes this monitor with
  // it. Only a service still warming up is left to finish.
  const stopped = (!health || stale) && lifecycle?.state !== "warming";
  const send = async (action: string) => {
    if (busy.current) return;
    busy.current = true;
    setConfirm("");
    setPending(action);
    setFeedback(undefined);
    if (action === "restart") onRestartingChange(true);
    try {
      const result = await request(
        ["start", "stop", "restart"].includes(action)
          ? `/lifecycle/${action}`
          : `/${action}`,
        { method: "POST", body: "{}" },
        lifecycleBudget(action) + clientMarginMilliseconds,
      );
      const outcome = text(
        result.message,
        action === "restart"
          ? "The service restarted."
          : "Service action completed.",
      );
      const notice = text(object(result.data).notice, "");
      setFeedback({
        failed: false,
        message: notice ? `${outcome} ${notice}` : outcome,
      });
    } catch (error) {
      setFeedback(
        action === "stop" && error instanceof MonitorUnreachableError
          ? { failed: false, message: stoppedWithMonitor }
          : {
              failed: true,
              message:
                error instanceof Error
                  ? error.message
                  : "Service action failed.",
            },
      );
    } finally {
      busy.current = false;
      setPending("");
      if (action === "restart") onRestartingChange(false);
      onRefresh();
    }
  };
  return (
    <Stack gap={3}>
      <Grid narrow className="monitor-grid monitor-control-grid">
        <Column sm={2} md={2} lg={4}>
          {stopped ? (
            <Button
              size="lg"
              kind="primary"
              disabled={Boolean(pending) || unreachable}
              onClick={() => void send("start")}
            >
              Start service
            </Button>
          ) : (
            <Button
              size="lg"
              kind="primary"
              disabled={Boolean(pending) || unreachable || !health || stale}
              onClick={() => setConfirm("restart")}
            >
              Restart service
            </Button>
          )}
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
              borrowed ||
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
            onClick={() => setConfirm("stop")}
          >
            Stop service
          </Button>
        </Column>
      </Grid>
      {borrowed && (
        <InlineNotification
          lowContrast
          hideCloseButton
          kind="info"
          title="Paused for a GPU borrower"
          subtitle="Another process, such as a GPU test run, borrowed the GPU and paused the service. It resumes on its own when that process finishes."
        />
      )}
      {pending && pending !== "restart" && (
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
        open={confirm === "restart"}
        modalHeading="Restart the RAG service?"
        primaryButtonText="Restart service"
        secondaryButtonText="Cancel"
        onRequestClose={() => setConfirm("")}
        onRequestSubmit={() => void send("restart")}
      >
        <p>
          Active work stops while the service restarts. This page stays open and
          reconnects on its own when the service is ready.
        </p>
      </Modal>
      <Modal
        open={confirm === "stop"}
        danger
        modalHeading="Stop the RAG service?"
        primaryButtonText="Stop service"
        secondaryButtonText="Cancel"
        onRequestClose={() => setConfirm("")}
        onRequestSubmit={() => void send("stop")}
      >
        <p>
          Active work will stop, and this monitor closes with the service. Run{" "}
          <code>vaultspec-rag server start</code> to start it again.
        </p>
      </Modal>
    </Stack>
  );
}
