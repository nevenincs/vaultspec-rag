import { useState } from "react";
import {
  Button,
  Column,
  Content,
  Grid,
  Header,
  HeaderName,
  SkipToContent,
  Stack,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Theme,
  Tile,
} from "@carbon/react";
import { activity, health, jobs, type Work } from "./model";
import { HealthCards } from "./Health";
import { Inspector } from "./Inspector";
import { JobLane, RequestLane } from "./Work";
import { Evidence, Logs } from "./Logs";
import { usePolling } from "./use-polling";
export function App() {
  const [paused, setPaused] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<Work | null>(null);
  const service = usePolling("/health", health, !paused, refresh);
  const indexing = usePolling("/jobs?limit=100", jobs, !paused, refresh);
  const serving = usePolling(
    "/search-activity?limit=100",
    activity,
    !paused,
    refresh,
  );
  const record =
    selected?.kind === "job"
      ? indexing.data?.records.find((row) => row.id === selected.id)
      : serving.data?.records.find((row) => row.request_id === selected?.id);
  const refreshNow = () => setRefresh((prior) => prior + 1);
  const inspect = (work: Work) => {
    setSelected(work);
    setTimeout(
      () =>
        document
          .getElementById("work-inspector")
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      0,
    );
  };
  return (
    <Theme theme="g100" className="monitor-root">
      <Header aria-label="Vaultspec RAG">
        <SkipToContent href="#main-content" />
        <HeaderName href="#main-content" prefix="Vaultspec">
          RAG monitor
        </HeaderName>
      </Header>
      <Content id="main-content" className="monitor-content">
        <Stack gap={8}>
          <Grid className="monitor-grid">
            <Column sm={4} md={8} lg={16}>
              <Stack gap={5}>
                <Stack
                  orientation="horizontal"
                  gap={5}
                  className="monitor-toolbar"
                >
                  <div>
                    <p className="cds--type-label-01 monitor-muted">
                      LOCAL OPERATOR INTERFACE
                    </p>
                    <h1 className="cds--type-heading-05">Service monitor</h1>
                  </div>
                  <Stack
                    orientation="horizontal"
                    gap={3}
                    className="monitor-controls"
                  >
                    <Button
                      kind="secondary"
                      size="md"
                      aria-pressed={paused}
                      onClick={() => setPaused(!paused)}
                    >
                      {paused ? "Resume live updates" : "Pause live updates"}
                    </Button>
                    <Button
                      kind="tertiary"
                      size="md"
                      disabled={paused}
                      onClick={refreshNow}
                    >
                      Refresh now
                    </Button>
                  </Stack>
                </Stack>
                <p className="cds--type-body-01 monitor-muted">
                  Health, indexing work and served requests from the service on
                  this machine.
                </p>
                <Evidence observation={service} paused={paused} />
              </Stack>
            </Column>
          </Grid>
          <HealthCards payload={service.data} />
          <Grid className="monitor-grid">
            <Column sm={4} md={8} lg={16}>
              <Stack gap={5}>
                <h2 className="cds--type-heading-03">Work</h2>
                <Tabs>
                  <TabList aria-label="Work lifecycle">
                    <Tab>Indexing jobs</Tab>
                    <Tab>Serving requests</Tab>
                  </TabList>
                  <TabPanels>
                    <TabPanel>
                      <Stack gap={5}>
                        <Evidence observation={indexing} paused={paused} />
                        <JobLane
                          data={indexing.data}
                          selected={selected}
                          onInspect={inspect}
                        />
                      </Stack>
                    </TabPanel>
                    <TabPanel>
                      <Stack gap={5}>
                        <Evidence observation={serving} paused={paused} />
                        <RequestLane
                          data={serving.data}
                          selected={selected}
                          onInspect={inspect}
                        />
                      </Stack>
                    </TabPanel>
                  </TabPanels>
                </Tabs>
              </Stack>
            </Column>
          </Grid>
          {selected && (
            <Grid className="monitor-grid">
              <Column sm={4} md={8} lg={16}>
                {record ? (
                  <Inspector
                    key={`${selected.kind}:${selected.id}`}
                    work={selected}
                    record={record}
                    paused={paused}
                    refresh={refresh}
                    stale={Boolean(
                      selected.kind === "job" ? indexing.error : serving.error,
                    )}
                    onRefresh={refreshNow}
                    onClose={() => setSelected(null)}
                  />
                ) : (
                  <Tile>
                    <Stack gap={4}>
                      <h2 className="cds--type-heading-03">
                        Work left the current page
                      </h2>
                      <p className="cds--type-body-01">
                        {selected.id} is no longer in this bounded observation.
                        Select a current record to inspect its logs.
                      </p>
                      <Button
                        kind="ghost"
                        size="sm"
                        onClick={() => setSelected(null)}
                      >
                        Close inspector
                      </Button>
                    </Stack>
                  </Tile>
                )}
              </Column>
            </Grid>
          )}
          <Grid className="monitor-grid">
            <Column sm={4} md={8} lg={16}>
              <Stack gap={5}>
                <h2 className="cds--type-heading-03">Service logs</h2>
                <p className="cds--type-body-01 monitor-muted">
                  Raw records grouped by producer. Job and request inspectors
                  show only their correlated service records.
                </p>
                <Logs paused={paused} refresh={refresh} />
              </Stack>
            </Column>
          </Grid>
        </Stack>
      </Content>
    </Theme>
  );
}
