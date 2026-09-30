import { open } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

const prefix = "/api/monitor";
const maxResponseBytes = 32 * 1024 * 1024;
const maxRequestBytes = 8192;

type Connection = { port: number; token: string };

function object(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function localHost(host: string): boolean {
  return (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host === "127.0.0.1" ||
    host === "[::1]"
  );
}

function localRequest(request: IncomingMessage): boolean {
  const address = request.socket.remoteAddress;
  if (!["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(address ?? "")) {
    return false;
  }
  const host = request.headers.host;
  if (!host) return false;
  try {
    const target = new URL(`http://${host}`);
    if (!localHost(target.hostname)) return false;
    const origin = request.headers.origin;
    return !origin || new URL(origin).host === target.host;
  } catch {
    return false;
  }
}

async function connection(): Promise<Connection> {
  const directory =
    process.env.VAULTSPEC_RAG_STATUS_DIR || join(homedir(), ".vaultspec-rag");
  let status: Record<string, unknown> = {};
  try {
    const file = await open(join(directory, "service.json"), "r");
    try {
      const buffer = Buffer.alloc(65537);
      const { bytesRead } = await file.read(buffer, 0, buffer.length, 0);
      if (bytesRead <= 65536)
        status = object(
          JSON.parse(buffer.subarray(0, bytesRead).toString("utf8")),
        );
    } finally {
      await file.close();
    }
  } catch {
    // A missing discovery file is normal while the local service is stopped.
  }
  const override = process.env.VAULTSPEC_RAG_PORT;
  const port = override ? Number(override) : status.port;
  if (
    typeof port !== "number" ||
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65535
  ) {
    throw new Error(
      "No local service is recorded. Start vaultspec-rag to see live work.",
    );
  }
  const token = status.service_token ?? status.token;
  return {
    port,
    token:
      typeof token === "string" && (!override || port === status.port)
        ? token
        : "",
  };
}

async function responseJSON(
  response: Response,
): Promise<Record<string, unknown>> {
  if (!response.body)
    throw new Error("The local service returned no response.");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxResponseBytes) {
        await reader.cancel();
        throw new Error(
          "The local service response exceeded the monitor window.",
        );
      }
      chunks.push(value);
    }
    const value: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("The local service returned an invalid response.");
    }
    return object(value);
  } finally {
    reader.releaseLock();
  }
}

async function requestBody(
  request: IncomingMessage,
  signal: AbortSignal,
): Promise<string> {
  const chunks: Buffer[] = [];
  let size = 0;
  const abort = () => request.destroy(new Error("The job action timed out."));
  signal.addEventListener("abort", abort, { once: true });
  try {
    signal.throwIfAborted();
    for await (const chunk of request) {
      const buffer = Buffer.isBuffer(chunk)
        ? chunk
        : Buffer.from(chunk as Uint8Array);
      size += buffer.byteLength;
      if (size > maxRequestBytes)
        throw new Error("The job action is too large.");
      chunks.push(buffer);
    }
  } finally {
    signal.removeEventListener("abort", abort);
  }
  const body = Buffer.concat(chunks).toString("utf8");
  JSON.parse(body);
  return body;
}

function allowedRoute(path: string, method: string): boolean {
  if (method === "GET") {
    return ["/health", "/jobs", "/search-activity", "/logs/json"].includes(
      path,
    );
  }
  const job = "/jobs/[a-zA-Z0-9_-]{1,128}";
  return (
    (method === "PUT" && new RegExp(`^${job}/desired-state$`).test(path)) ||
    (method === "POST" && new RegExp(`^${job}/retry$`).test(path)) ||
    (method === "DELETE" && new RegExp(`^${job}$`).test(path))
  );
}

function reply(
  response: ServerResponse,
  status: number,
  body: Record<string, unknown>,
): void {
  if (response.destroyed) return;
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(JSON.stringify(body));
}

async function forward(
  request: IncomingMessage,
  response: ServerResponse,
): Promise<void> {
  if (!localRequest(request)) {
    reply(response, 403, {
      ok: false,
      message: "The monitor connects on this machine only.",
    });
    return;
  }
  const route = new URL(request.url ?? "/", "http://127.0.0.1");
  route.pathname = route.pathname.slice(prefix.length);
  const method = request.method ?? "GET";
  if (!allowedRoute(route.pathname, method)) {
    reply(response, 404, { ok: false, message: "Unknown monitor operation." });
    return;
  }
  const controller = new AbortController();
  response.once("close", () => controller.abort());
  const signal = AbortSignal.any([
    controller.signal,
    AbortSignal.timeout(5000),
  ]);
  try {
    const local = await connection();
    const base = `http://127.0.0.1:${local.port}`;
    const body =
      method === "PUT" || method === "POST"
        ? await requestBody(request, signal)
        : undefined;
    const send = (token: string) =>
      fetch(`${base}${route.pathname}${route.search}`, {
        method,
        body,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        redirect: "error",
        signal,
      });
    let result = await send(local.token);
    let payload = await responseJSON(result);
    if (result.status === 401) {
      const health = await responseJSON(
        await fetch(`${base}/health`, { signal, redirect: "error" }),
      );
      const token = health.service_token;
      if (typeof token === "string" && token) {
        result = await send(token);
        payload = await responseJSON(result);
      }
    }
    delete payload.service_token;
    delete payload.token;
    reply(response, result.status, payload);
  } catch (error) {
    const message =
      error instanceof Error && error.message.startsWith("No local service")
        ? error.message
        : "The local service did not answer. Previous observations remain visible.";
    reply(response, 503, { ok: false, message });
  }
}

export function monitorMiddleware(
  request: IncomingMessage,
  response: ServerResponse,
  next: () => void,
): void {
  if (request.url?.startsWith(`${prefix}/`)) {
    void forward(request, response);
  } else {
    next();
  }
}

export function localServicePlugin(): Plugin {
  return {
    name: "local-rag-monitor",
    configureServer(server) {
      server.middlewares.use(monitorMiddleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use(monitorMiddleware);
    },
  };
}
