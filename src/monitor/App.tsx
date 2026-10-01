import { Awake, Asleep, Screen, Renew } from "@carbon/icons-react";
import { useEffect, useState } from "react";
import {
  Column,
  Content,
  Grid,
  Header,
  HeaderMenuButton,
  HeaderName,
  HeaderGlobalBar,
  HeaderGlobalAction,
  usePrefersDarkScheme,
  Tag,
  Tile,
  InlineNotification,
  SideNav,
  SideNavItems,
  SideNavLink,
  SkipToContent,
  Stack,
  Theme,
  GlobalTheme,
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
    <Tag type="gray" size="sm" className="monitor-freshness">
      {age === null
        ? "Not updated yet"
        : `${paused || observation.error ? "Last update" : "Updated"} ${age}s ago · ${new Date(observation.observedAt!).toLocaleTimeString()}`}
    </Tag>
  );
}
export function App() {
  const [page, setPage] = useState<Page>(locationPage);
  const [desktop, setDesktop] = useState(
    () => matchMedia("(min-width: 66rem)").matches,
  );
  const [nav, setNav] = useState(
    () => matchMedia("(min-width: 66rem)").matches,
  );
  const [themeSetting, setThemeSetting] = useState<"light" | "system" | "dark">(
    () => {
      try {
        const saved = localStorage.getItem("monitor-theme");
        return saved === "light" || saved === "dark" ? saved : "system";
      } catch {
        return "system";
      }
    },
  );
  const prefersDark = usePrefersDarkScheme();
  const theme =
    themeSetting === "dark" || (themeSetting === "system" && prefersDark)
      ? "g100"
      : "g10";
  const nextTheme = (
    { light: "dark", dark: "system", system: "light" } as const
  )[themeSetting];
  const ThemeIcon = { light: Awake, dark: Asleep, system: Screen }[
    themeSetting
  ];
  useEffect(() => {
    const media = matchMedia("(min-width: 66rem)");
    const change = () => {
      setDesktop(media.matches);
      setNav(media.matches);
    };
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("monitor-theme", themeSetting);
    } catch {
      /* Storage can be disabled. */
    }
  }, [themeSetting]);
  const [paused, setPaused] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const change = () => {
      setPage(locationPage());
      if (!matchMedia("(min-width: 66rem)").matches) setNav(false);
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
  const lifecycleState = lifecycle.error
    ? "unavailable"
    : text(lifecycle.data?.state, "connecting");
  const serviceStatus = service.error
    ? lifecycleState
    : service.data
      ? text(object(service.data.quiesce).state) === "running"
        ? text(service.data.status, "unknown")
        : text(object(service.data.quiesce).state, text(service.data.status))
      : "connecting";
  const offline = Boolean(service.error);
  const serviceLabel =
    (
      {
        ready: "Service running",
        degraded: "Service degraded",
        error: "Service error",
        quiesced: "Service paused",
        draining: "Service pausing",
        stopped: "Service not running",
        crashed: "Service stopped unexpectedly",
        warming: "Service starting",
        connecting: "Checking service",
        unavailable: "Cannot connect to service",
        divergent: "Service needs attention",
      } as Record<string, string>
    )[serviceStatus] ?? serviceStatus.replaceAll("_", " ");
  const runtime = usePolling(
    "/runtime-observations",
    object,
    !paused &&
      !offline &&
      ["dashboard", "performance", "clients"].includes(page),
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
    <GlobalTheme theme={theme}>
      <Theme
        theme={theme}
        className={`monitor-root ${desktop && nav ? "monitor-nav-open" : ""}`}
      >
        <Header aria-label="Vaultspec RAG" className="monitor-header">
          <SkipToContent href="#main-content" />
          <HeaderMenuButton
            aria-label={nav ? "Close navigation" : "Open navigation"}
            onClick={() => setNav(!nav)}
            isActive={nav}
            className="monitor-nav-toggle"
            isCollapsible
            aria-expanded={nav}
            aria-controls="monitor-navigation"
          />
          <HeaderName
            href="#/dashboard"
            prefix="Vaultspec"
            className="monitor-brand"
          >
            RAG
          </HeaderName>
          <HeaderGlobalBar className="monitor-header-actions">
            <HeaderGlobalAction
              className="monitor-refresh"
              aria-label={
                paused ? "Refresh and resume live updates" : "Refresh"
              }
              tooltipAlignment="end"
              onClick={() => {
                setPaused(false);
                refreshNow();
              }}
            >
              <Renew size={20} />
            </HeaderGlobalAction>
            <HeaderGlobalAction
              className="monitor-theme"
              aria-label={`Theme: ${themeSetting}. Switch to ${nextTheme}`}
              tooltipAlignment="end"
              onClick={() => setThemeSetting(nextTheme)}
            >
              <ThemeIcon size={20} />
            </HeaderGlobalAction>
          </HeaderGlobalBar>
          <Stack
            orientation={desktop ? "horizontal" : "vertical"}
            gap={3}
            className="monitor-header-details"
          >
            <Stack
              orientation="horizontal"
              gap={3}
              className="monitor-observation-group"
            >
              <span className="cds--type-label-01 monitor-version">
                v{text(service.data?.package_version, "—")}
              </span>
              <Freshness observation={service} paused={paused} />
            </Stack>
            <Stack
              orientation="horizontal"
              gap={5}
              className="monitor-update-controls"
            >
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
            </Stack>
          </Stack>
          <SideNav
            aria-label="Monitor navigation"
            expanded={nav}
            id="monitor-navigation"
            className="monitor-navigation"
            isPersistent={false}
            isFixedNav={desktop}
            addMouseListeners={false}
            addFocusListeners={false}
            onOverlayClick={() => setNav(false)}
          >
            <SideNavItems>
              {Object.entries(pages).map(([key, label]) => (
                <SideNavLink
                  key={key}
                  href={`#/${key}`}
                  isActive={page === key}
                >
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
                    <Status state={serviceStatus} label={serviceLabel} />
                  </Stack>
                  <div hidden={page !== "dashboard"}>
                    <ServiceControls
                      health={offline ? undefined : service.data}
                      state={offline ? undefined : state.data}
                      lifecycle={lifecycle.data}
                      stale={Boolean(service.error || state.error)}
                      onRefresh={refreshNow}
                    />
                  </div>
                  {offline && ["stopped", "warming"].includes(serviceStatus) ? (
                    <Tile id="service-state-notice">
                      <p>
                        {serviceStatus === "stopped"
                          ? "Start the service to resume indexing and queries."
                          : "Models and storage are loading. This page updates automatically."}
                      </p>
                    </Tile>
                  ) : offline ? (
                    <InlineNotification
                      lowContrast
                      kind={serviceStatus === "stopped" ? "info" : "warning"}
                      id="service-state-notice"
                      title={serviceLabel}
                      subtitle={
                        serviceStatus === "stopped"
                          ? "Start the service to resume indexing and queries."
                          : serviceStatus === "warming"
                            ? "Models and storage are loading. This page updates automatically."
                            : (lifecycle.error ??
                              "Checking the local service process. Live metrics are unavailable.")
                      }
                      hideCloseButton
                    />
                  ) : (
                    pageObservation.error && (
                      <InlineNotification
                        lowContrast
                        kind="warning"
                        title="Unable to update data"
                        subtitle={pageObservation.error}
                        hideCloseButton
                      />
                    )
                  )}
                </Stack>
              </Column>
            </Grid>
            {page === "dashboard" && !offline && (
              <>
                <ResourceMetrics
                  key={`${desktop}-${nav}`}
                  payload={runtime.data}
                />
                {runtime.error && (
                  <Grid narrow className="monitor-grid">
                    <Column sm={4} md={8} lg={16}>
                      <Evidence observation={runtime} paused={paused} />
                    </Column>
                  </Grid>
                )}
                <HealthCards payload={service.data} runtime={runtime.data} />
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
                  {page === "logs" && (
                    <Logs paused={paused} refresh={refresh} />
                  )}
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
                        Active service connections. Connections through this
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
                      <ResourceMetrics
                        key={`${desktop}-${nav}`}
                        payload={runtime.data}
                      />
                      <DataTree
                        value={runtime.data ?? { status: "Loading metrics…" }}
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
    </GlobalTheme>
  );
}
