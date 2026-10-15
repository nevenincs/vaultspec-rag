import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createServer as createPortProbe, type Server } from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { monitorAccess, monitorMiddleware } from "./local-service.ts";
import manifest from "../../../package.json" with { type: "json" };

export type EmbeddedAsset = {
  body: Uint8Array;
  content_type: string;
  sha256: string;
};

export type MonitorBuild = {
  version: string;
  source_revision: string;
  lock_sha256: string;
  frontend_sha256: string;
  bun_version: string;
  development: boolean;
};

type Options = {
  port: number;
  managed: boolean;
  version: boolean;
  json: boolean;
};

function options(args: string[]): Options {
  const result = {
    port: manifest.portless.appPort,
    managed: false,
    version: false,
    json: false,
  };
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === "--managed") result.managed = true;
    else if (arg === "--version") result.version = true;
    else if (arg === "--json") result.json = true;
    else if (arg === "--port") {
      const port = args[++index];
      if (
        !port ||
        !/^\d+$/.test(port) ||
        Number(port) < 1 ||
        Number(port) > 65535
      )
        throw new Error("--port must be an integer from 1 to 65535.");
      result.port = Number(port);
    } else throw new Error(`Unknown monitor argument: ${arg}`);
  }
  return result;
}

function listen(server: Server, port: number, host: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const ready = () => {
      server.removeListener("error", error);
      resolve();
    };
    const error = (reason: Error) => {
      server.removeListener("listening", ready);
      reject(reason);
    };
    server.once("error", error);
    server.listen(port, host, ready);
  });
}

async function requireLoopbackPort(port: number): Promise<void> {
  // BSD can bind a wildcard listener beside an existing specific-address listener.
  // Reserve the client address first so readiness cannot point at another process.
  const probe = createPortProbe((socket) => socket.destroy());
  await listen(probe, port, "127.0.0.1");
  await new Promise<void>((resolve, reject) => {
    probe.close((error) => (error ? reject(error) : resolve()));
  });
}

async function bind(server: Server, selected: Options): Promise<number> {
  for (let port = selected.port; port <= 65535; port++) {
    try {
      await requireLoopbackPort(port);
      await listen(server, port, manifest.devserver.host);
      return port;
    } catch (error) {
      if (
        !selected.managed ||
        !(error instanceof Error) ||
        !("code" in error) ||
        error.code !== "EADDRINUSE"
      )
        throw error;
    }
  }
  throw new Error("No monitor port is available above the backend port.");
}

// The daemon writes this down the ownership pipe before a restart releases the
// monitor; the EOF that follows then hands it to the next daemon instead of
// closing it.
const handoffLine = "vaultspec.monitor.handoff";

function ownerAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** Whether the identity record still keeps this released monitor open. */
async function stillOwned(): Promise<boolean> {
  const directory =
    process.env.VAULTSPEC_RAG_STATUS_DIR || join(homedir(), ".vaultspec-rag");
  let record: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(
      await readFile(join(directory, "monitor.json"), "utf8"),
    );
    if (typeof parsed !== "object" || parsed === null) return false;
    record = parsed as Record<string, unknown>;
  } catch {
    return false;
  }
  if (record.pid !== process.pid) return false;
  const until = record.handoff_until;
  if (typeof until === "number" && until > 0) return Date.now() / 1000 < until;
  return typeof record.owner_pid === "number" && ownerAlive(record.owner_pid);
}

/** After a handoff no pipe ties the monitor to a daemon, so it watches the
 * record the adopting daemon rewrites and closes once nothing owns it. */
function watchOwner(stop: () => void): void {
  const check = async () => {
    if (await stillOwned()) setTimeout(() => void check(), 1000);
    else stop();
  };
  void check();
}

export async function startMonitor(
  assets: ReadonlyMap<string, EmbeddedAsset>,
  build: MonitorBuild,
): Promise<void> {
  const selected = options(process.argv.slice(2));
  if (selected.version) {
    console.log(
      selected.json
        ? JSON.stringify({ command: "vaultspec-rag-monitor", ...build })
        : `vaultspec-rag-monitor ${build.version}${build.development ? " (development build)" : ""} (${build.source_revision})`,
    );
    return;
  }
  const server = createServer((request, response) => {
    monitorMiddleware(request, response, () => {
      let path: string;
      try {
        path = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
      } catch {
        response.writeHead(400);
        response.end();
        return;
      }
      if (request.method !== "GET" && request.method !== "HEAD") {
        response.writeHead(405, { Allow: "GET, HEAD" });
        response.end();
        return;
      }
      if (path === "/monitor.json") {
        response.writeHead(200, {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff",
        });
        response.end(
          request.method === "HEAD"
            ? undefined
            : JSON.stringify({
                ...build,
                assets: Object.fromEntries(
                  [...assets].map(([name, asset]) => [
                    name,
                    {
                      sha256: asset.sha256,
                      size: asset.body.byteLength,
                      content_type: asset.content_type,
                    },
                  ]),
                ),
              }),
        );
        return;
      }
      const asset = assets.get(path === "/" ? "/index.html" : path);
      if (!asset) {
        response.writeHead(404);
        response.end();
        return;
      }
      response.writeHead(200, {
        "Content-Type": asset.content_type,
        "Content-Length": asset.body.byteLength,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
      response.end(request.method === "HEAD" ? undefined : asset.body);
    });
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 5000;
  const port = await bind(server, selected);
  let stopping = false;
  const stop = () => {
    if (stopping) return;
    stopping = true;
    const deadline = setTimeout(() => {
      server.closeAllConnections();
      process.exit(0);
    }, 2500);
    server.close(() => {
      clearTimeout(deadline);
      process.stdin.pause();
      process.exit(0);
    });
    server.closeIdleConnections();
  };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  if (selected.managed) {
    let handedOff = false;
    let buffered = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk: string) => {
      buffered += chunk;
      const lines = buffered.split("\n");
      buffered = lines.pop() ?? "";
      if (lines.some((line) => line.trim() === handoffLine)) {
        handedOff = true;
        // The releasing daemon owns the read end of this output and is about
        // to exit; a later write must not take the monitor down with it.
        process.stdout.on("error", () => undefined);
        process.stderr.on("error", () => undefined);
      }
    });
    process.stdin.once("end", () => {
      if (handedOff) watchOwner(stop);
      else stop();
    });
    process.stdin.resume();
  }
  console.log(`vaultspec.monitor.ready ${monitorAccess(port)}`);
}
