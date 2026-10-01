import { useEffect, useState } from "react";
import {
  Button,
  Column,
  Content,
  Grid,
  Header,
  HeaderMenuButton,
  HeaderName,
  InlineLoading,
  InlineNotification,
  SideNav,
  SideNavItems,
  SideNavLink,
  SkipToContent,
  Stack,
  Theme,
  Toggle,
} from "@carbon/react";
import { activity, health, jobs, object, text } from "./model";
import { HealthCards, ResourceMetrics, ServiceDiagnostics } from "./Health";
import { WorkPage } from "./Work";
import { Logs, Evidence } from "./Logs";
import { usePolling, type Observation } from "./use-polling";
import { ServiceControls } from "./ServiceControls";
import { DataTree } from "./DataTree";
import { InventoryPage } from "./Inventory";
import { Status } from "./presentation";

const pages = {
  dashboard: "Dashboard",
  indexing: "Index Requests",
  queries: "Queries",
  repositories: "Repositories",
  storage: "Storage",
  clients: "Clients",
  performance: "Performance",
  logs: "Logs",
};
type Page = keyof typeof pages;
function locationPage(): Page {
  const key = location.hash.slice(2);
  return key in pages ? (key as Page) : "dashboard";
}
function Freshness({
  observation,
  paused,
}: {
  observation: Observation<unknown>;
  paused: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const age = observation.observedAt
    ? Math.max(0, Math.floor((now - observation.observedAt) / 1000))
    : null;
  return (
    <InlineLoading
      className="monitor-freshness"
      status={
        observation.error
          ? "error"
          : paused
            ? "inactive"
            : age === null
              ? "active"
              : "finished"
      }
      description={
        age === null
          ? "Waiting for service"
          : `Updated ${age}s ago · ${new Date(observation.observedAt!).toLocaleTimeString()}`
      }
    />
  );
}
export function App() {
  const [page, setPage] = useState<Page>(locationPage);
  const [nav, setNav] = useState(false);
  const [paused, setPaused] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const change = () => {
      setPage(locationPage());
      setNav(false);
      document.getElementById("page-heading")?.focus();
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  const service = usePolling("/health", health, !paused, refresh);
  const lifecycle = usePolling(
    "/lifecycle",
    object,
    !paused && Boolean(service.error),
    refresh,
    10000,
    35000,
  );
  const state = service;
  const serviceStatus = service.error
    ? text(lifecycle.data?.state, "unavailable")
    : text(service.data?.status, "unknown");
  const runtime = usePolling(
    "/runtime-observations",
    object,
    !paused && ["dashboard", "performance", "clients"].includes(page),
    refresh,
    3000,
  );
  const indexing = usePolling(
    "/jobs?limit=100",
    jobs,
    !paused && page === "indexing",
    refresh,
  );
  const serving = usePolling(
    "/search-activity?limit=100",
    activity,
    !paused && page === "queries",
    refresh,
  );
  const refreshNow = () => setRefresh((value) => value + 1);
  const pageObservation =
    page === "indexing"
      ? indexing
      : page === "queries"
        ? serving
        : ["performance", "clients"].includes(page)
          ? runtime
          : service;
  return (
    <Theme theme="g100" className="monitor-root">
      <Header aria-label="Vaultspec RAG" className="monitor-header">
        <SkipToContent href="#main-content" />
        <HeaderMenuButton
          aria-label={nav ? "Close navigation" : "Open navigation"}
          onClick={() => setNav(!nav)}
          isActive={nav}
        />
        <HeaderName href="#/dashboard" prefix="Vaultspec">
          RAG
        </HeaderName>
        <Stack
          orientation="horizontal"
          gap={5}
          className="monitor-header-details"
        >
          <span className="cds--type-label-01">
            v{text(service.data?.package_version, "—")}
          </span>
          <Freshness observation={service} paused={paused} />
          <Toggle
            id="live-updates"
            labelText="Live updates"
            hideLabel
            labelA="Paused"
            labelB="Live updates"
            size="sm"
            toggled={!paused}
            onToggle={(enabled) => setPaused(!enabled)}
          />
          <Button kind="ghost" size="sm" disabled={paused} onClick={refreshNow}>
            Refresh
          </Button>
        </Stack>
        <SideNav
          aria-label="Monitor navigation"
          expanded={nav}
          isPersistent
          onOverlayClick={() => setNav(false)}
        >
          <SideNavItems>
            {Object.entries(pages).map(([key, label]) => (
              <SideNavLink key={key} href={`#/${key}`} isActive={page === key}>
                {label}
              </SideNavLink>
            ))}
          </SideNavItems>
        </SideNav>
      </Header>
      <Content id="main-content" className="monitor-content">
        <Stack gap={6}>
          <Grid narrow className="monitor-grid">
            <Column sm={4} md={8} lg={16}>
              <Stack gap={5}>
                <Stack
                  orientation="horizontal"
                  gap={5}
                  className="monitor-toolbar"
                >
                  <h1
                    id="page-heading"
                    tabIndex={-1}
                    className="cds--type-heading-04"
                  >
                    {pages[page]}
                  </h1>
                  <Status
                    state={
                      service.error
                        ? serviceStatus
                        : text(object(state.data?.quiesce).state, serviceStatus)
                    }
                  />
                </Stack>
                <div hidden={page !== "dashboard"}>
                  <ServiceControls
                    health={service.data}
                    state={state.data}
                    lifecycle={lifecycle.data}
                    stale={Boolean(service.error || state.error)}
                    onRefresh={refreshNow}
                  />
                </div>
                {pageObservation.error && (
                  <InlineNotification
                    kind="warning"
                    title="Observation unavailable"
                    subtitle={pageObservation.error}
                    hideCloseButton
                  />
                )}
              </Stack>
            </Column>
          </Grid>
          {page === "dashboard" && (
            <>
              <ResourceMetrics payload={runtime.data} />
              {runtime.error && (
                <Grid narrow className="monitor-grid">
                  <Column sm={4} md={8} lg={16}>
                    <Evidence observation={runtime} paused={paused} />
                  </Column>
                </Grid>
              )}
              <HealthCards
                payload={service.data}
                runtime={runtime.data}
                status={serviceStatus}
              />
              <ServiceDiagnostics
                health={service.data}
                runtime={runtime.data}
              />
            </>
          )}
          {page !== "dashboard" && (
            <Grid narrow className="monitor-grid">
              <Column sm={4} md={8} lg={16}>
                {page === "indexing" && (
                  <WorkPage
                    kind="job"
                    data={indexing.data}
                    paused={paused}
                    stale={Boolean(indexing.error)}
                    refresh={refresh}
                    onRefresh={refreshNow}
                  />
                )}
                {page === "queries" && (
                  <WorkPage
                    kind="request"
                    data={serving.data}
                    paused={paused}
                    stale={Boolean(serving.error)}
                    refresh={refresh}
                    onRefresh={refreshNow}
                  />
                )}
                {page === "logs" && <Logs paused={paused} refresh={refresh} />}
                {(page === "repositories" || page === "storage") && (
                  <InventoryPage
                    key={page}
                    kind={page}
                    paused={paused}
                    refresh={refresh}
                    onRefresh={refreshNow}
                  />
                )}
                {page === "clients" && (
                  <Stack gap={5}>
                    <p className="monitor-muted">
                      Observed service TCP connections. Connections through this
                      monitor appear as its local bridge.
                    </p>
                    <DataTree
                      value={object(runtime.data?.clients)}
                      label="Connected clients"
                    />
                  </Stack>
                )}
                {page === "performance" && (
                  <Stack gap={6}>
                    <ResourceMetrics payload={runtime.data} />
                    <DataTree
                      value={
                        runtime.data ?? { observation: "Waiting for metrics" }
                      }
                      label="Resource diagnostics"
                    />
                  </Stack>
                )}
              </Column>
            </Grid>
          )}
        </Stack>
      </Content>
    </Theme>
  );
}
