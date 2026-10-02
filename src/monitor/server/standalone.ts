import { createServer, type Server } from "node:http";
import { monitorMiddleware } from "./local-service.ts";
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

function listen(server: Server, port: number): Promise<void> {
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
    server.listen(port, manifest.devserver.host, ready);
  });
}

async function bind(server: Server, selected: Options): Promise<number> {
  for (let port = selected.port; port <= 65535; port++) {
    try {
      await listen(server, port);
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
    process.stdin.once("end", stop);
    process.stdin.resume();
  }
  console.log(`vaultspec.monitor.ready ${port}`);
}
