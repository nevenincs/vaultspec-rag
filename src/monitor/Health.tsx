import { Column, Grid, Stack, Tile } from "@carbon/react";
import { number, object, reading, text, type RecordValue } from "./model";
import { Details, Status } from "./presentation";
const typesafeDescriptions: Record<string, string> = {
  off: "No API key enrolled. Searches use standard ranking.",
  pending: "Enrolled and waiting for the first successful classified search.",
  active: "Recent searches were classified.",
  rejected: "The enrolled key was rejected. Searches use standard ranking.",
  cooldown:
    "Classification is paused after errors. Searches use standard ranking for now.",
};

export function HealthCards({ payload }: { payload?: RecordValue }) {
  const features = object(payload?.features);
  const typesafe = object(features.typesafe);
  const state = text(payload?.status, "unknown");
  const typesafeState = text(typesafe.state, "unknown");
  const degradations = Array.isArray(payload?.degradations)
    ? payload.degradations
    : [];
  const backend = object(payload?.qdrant);
  return (
    <Grid narrow className="monitor-grid">
      <Column sm={4} md={4} lg={6}>
        <Tile className="monitor-health-tile">
          <Stack gap={5}>
            <h2 className="cds--type-heading-compact-02">Service health</h2>
            <Status state={state} />
            <Details
              items={[
                ["Process", reading(payload?.pid)],
                ["Uptime", reading(payload?.uptime_s, " s")],
                [
                  "Models",
                  payload?.models_loaded === true
                    ? "Loaded"
                    : payload?.models_loaded === false
                      ? "Not loaded"
                      : "Not reported",
                ],
                ["Projects", reading(payload?.project_count)],
              ]}
            />
            {degradations.length > 0 && (
              <ul className="monitor-reasons cds--type-body-compact-01">
                {degradations.map((raw, index) => (
                  <li key={index}>
                    {typeof raw === "string"
                      ? raw
                      : text(object(raw).detail, text(object(raw).reason))}
                  </li>
                ))}
              </ul>
            )}
          </Stack>
        </Tile>
      </Column>
      <Column sm={4} md={4} lg={6}>
        <Tile className="monitor-health-tile">
          <Stack gap={5}>
            <h2 id="typesafe-heading" className="cds--type-heading-compact-02">
              TypeSafe classification
            </h2>
            <Status state={typesafeState} />
            <p className="cds--type-body-compact-01">
              {typesafeDescriptions[typesafeState] ??
                "The service has not reported classification state."}
            </p>
            <Details
              items={[
                ["Model", text(typesafe.model)],
                [
                  "Last successful classification",
                  number(typesafe.last_success_age_seconds) === null
                    ? "Not reported"
                    : `${reading(typesafe.last_success_age_seconds, " s")} ago`,
                ],
                ["Retry after", reading(typesafe.retry_after_seconds, " s")],
              ]}
            />
          </Stack>
        </Tile>
      </Column>
      <Column sm={4} md={8} lg={4}>
        <Tile className="monitor-health-tile">
          <Stack gap={5}>
            <h2 className="cds--type-heading-compact-02">Service features</h2>
            <Details
              items={[
                ["Storage", text(features.storage_backend)],
                ["Qdrant", text(backend.status)],
                [
                  "Watcher",
                  features.watcher_enabled === true
                    ? "Enabled"
                    : features.watcher_enabled === false
                      ? "Disabled"
                      : "Not reported",
                ],
                [
                  "Reranker",
                  features.reranker_enabled === false
                    ? "Disabled"
                    : features.reranker_loaded === true
                      ? "Loaded"
                      : features.reranker_loaded === false
                        ? "Not loaded"
                        : "Not reported",
                ],
                ["Version", text(payload?.package_version)],
              ]}
            />
          </Stack>
        </Tile>
      </Column>
    </Grid>
  );
}
