import { Column, Grid, Stack, Tile } from "@carbon/react";
import { MeterChart } from "@carbon/charts-react";
import { number, object, reading, text, type RecordValue } from "./model";
import { Details, Status } from "./presentation";

export function ResourceMetrics({ payload }: { payload?: RecordValue }) {
  const cpu = object(payload?.cpu),
    ram = object(payload?.ram),
    gpu = object(payload?.gpu),
    disk = object(payload?.disk);
  const totalRam = number(ram.total_bytes),
    availableRam = number(ram.available_bytes);
  const ratio = (used: unknown, total: unknown) => {
    const u = number(used),
      t = number(total);
    return u !== null && t !== null && t > 0
      ? Math.min(100, (u / t) * 100)
      : null;
  };
  const metrics = [
    {
      label: "System CPU",
      value: number(cpu.system_utilization_percent),
      detail: `Service CPU ${reading(cpu.utilization_percent, "%")} · one-core basis`,
    },
    {
      label: "System RAM",
      value: ratio(
        totalRam !== null && availableRam !== null
          ? totalRam - availableRam
          : null,
        totalRam,
      ),
      detail: `Service ${bytes(ram.process_rss_bytes)} · Available ${bytes(ram.available_bytes)}`,
    },
    {
      label: "GPU memory",
      value: ratio(gpu.memory_used_mib, gpu.memory_total_mib),
      detail: `${reading(gpu.memory_used_mib)} / ${reading(gpu.memory_total_mib)} MiB · GPU ${reading(gpu.utilization_percent, "%")}`,
    },
    {
      label: "Storage disk",
      value: ratio(disk.used_bytes, disk.total_bytes),
      detail: `${bytes(disk.free_bytes)} free of ${bytes(disk.total_bytes)}`,
    },
  ];
  return (
    <Grid narrow className="monitor-grid">
      {metrics.map((metric) => (
        <Column key={metric.label} sm={4} md={4} lg={4}>
          <Tile className="monitor-health-tile">
            <Stack gap={4}>
              <h2 className="cds--type-heading-compact-01">{metric.label}</h2>
              {metric.value === null ? (
                <p className="monitor-reading">Not reported</p>
              ) : (
                <MeterChart
                  data={[{ group: metric.label, value: metric.value }]}
                  options={{
                    title: `${reading(metric.value, "%")} used`,
                    height: "88px",
                    theme: "g100",
                    toolbar: { enabled: false },
                    meter: { peak: 100 },
                    animations: false,
                  }}
                />
              )}
              <p className="cds--type-label-01 monitor-muted">
                {metric.detail}
              </p>
            </Stack>
          </Tile>
        </Column>
      ))}
    </Grid>
  );
}

export function bytes(value: unknown): string {
  const amount = number(value);
  if (amount === null) return "Not reported";
  if (amount < 1024) return `${amount} B`;
  const unit = Math.min(4, Math.floor(Math.log(amount) / Math.log(1024)));
  return `${Number((amount / 1024 ** unit).toFixed(1))} ${["B", "KiB", "MiB", "GiB", "TiB"][unit]}`;
}

export function HealthCards({
  payload,
  runtime,
  status,
}: {
  payload?: RecordValue;
  runtime?: RecordValue;
  status: string;
}) {
  const features = object(payload?.features),
    backend = object(payload?.qdrant),
    models = object(runtime?.models),
    typesafe = object(features.typesafe);
  return (
    <Grid narrow className="monitor-grid">
      <Column sm={4} md={4} lg={8}>
        <Tile className="monitor-health-tile">
          <Stack gap={5}>
            <h2 className="cds--type-heading-compact-02">Service overview</h2>
            <Status state={status} />
            <Details
              items={[
                ["Process", reading(payload?.pid)],
                ["Uptime", reading(payload?.uptime_s, " s")],
                ["Resident repositories", reading(payload?.project_count)],
                ["Storage backend", text(features.storage_backend)],
                [
                  "Qdrant",
                  backend.alive === true
                    ? "Running"
                    : backend.alive === false
                      ? "Stopped"
                      : text(backend.mode),
                ],
                [
                  "Watcher",
                  features.watcher_enabled === true
                    ? "Enabled"
                    : features.watcher_enabled === false
                      ? "Disabled"
                      : "Not reported",
                ],
              ]}
            />
            {Array.isArray(payload?.degradations) &&
              payload.degradations.length > 0 && (
                <ul className="monitor-reasons">
                  {payload.degradations.map((item, index) => (
                    <li key={index}>
                      {typeof item === "string"
                        ? item
                        : text(object(item).detail, text(object(item).reason))}
                    </li>
                  ))}
                </ul>
              )}
          </Stack>
        </Tile>
      </Column>
      <Column sm={4} md={4} lg={8}>
        <Tile className="monitor-health-tile">
          <Stack gap={5}>
            <h2 className="cds--type-heading-compact-02">
              Models and integrations
            </h2>
            <Details
              items={[
                [
                  "Embedding model",
                  text(
                    object(models.embedding).loaded_name ??
                      features.embedding_model ??
                      payload?.embedding_model,
                  ),
                ],
                [
                  "Reranking model",
                  text(
                    object(models.reranker).loaded_name ??
                      features.reranker_model ??
                      payload?.reranker_model,
                  ),
                ],
                ["Sparse model", text(features.sparse_model, "Disabled")],
                [
                  "Model residency",
                  payload?.models_loaded === true
                    ? "Loaded"
                    : payload?.models_loaded === false
                      ? "Not loaded"
                      : "Not reported",
                ],
                [
                  "TypeSafe API",
                  typesafe.state === "off" || typesafe.enabled === false
                    ? "Not configured"
                    : typeof typesafe.state === "string" ||
                        typesafe.enabled === true
                      ? "Enabled"
                      : "Not reported",
                ],
              ]}
            />
          </Stack>
        </Tile>
      </Column>
    </Grid>
  );
}

export function ServiceDiagnostics({
  health,
  runtime,
}: {
  health?: RecordValue;
  runtime?: RecordValue;
}) {
  const quiesce = object(health?.quiesce),
    pools = object(runtime?.pools);
  return (
    <Grid narrow className="monitor-grid">
      <Column sm={4} md={4} lg={8}>
        <Tile className="monitor-health-tile">
          <Stack gap={4}>
            <h2 className="cds--type-heading-compact-02">Service state</h2>
            <Details
              items={[
                ["Admission state", text(quiesce.state)],
                [
                  "Admission",
                  quiesce.admissions_open === true
                    ? "Open"
                    : quiesce.admissions_open === false
                      ? "Closed"
                      : "Not reported",
                ],
                [
                  "Compute in progress",
                  reading(quiesce.active_compute_tickets),
                ],
                [
                  "GPU borrower hold",
                  quiesce.borrower_bound === true
                    ? "Held by borrower"
                    : quiesce.borrower_bound === false
                      ? "None"
                      : "Not reported",
                ],
                [
                  "State detail",
                  text(quiesce.failure_reason, "No failure reported"),
                ],
                [
                  "Observed connections",
                  reading(object(runtime?.clients).total),
                ],
                ["Storage path", text(object(runtime?.disk).path)],
              ]}
            />
          </Stack>
        </Tile>
      </Column>
      <Column sm={4} md={4} lg={8}>
        <Tile className="monitor-health-tile">
          <Stack gap={4}>
            <h2 className="cds--type-heading-compact-02">Service capacity</h2>
            <Details
              items={["search", "index", "encode"].map((name) => {
                const pool = object(pools[name]);
                return [
                  name === "search"
                    ? "Query seats"
                    : name === "index"
                      ? "Index seats"
                      : "Encoding seats",
                  `${reading(pool.borrowed_tokens)} / ${reading(pool.total_tokens)} used · ${reading(pool.waiting)} waiting`,
                ] as [string, string];
              })}
            />
          </Stack>
        </Tile>
      </Column>
    </Grid>
  );
}
