import { execFile } from "node:child_process";
import { access, open } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";
import { isIP } from "node:net";
import { fileURLToPath } from "node:url";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import manifest from "../../../package.json" with { type: "json" };

const prefix = "/api/monitor";
const maxResponseBytes = 32 * 1024 * 1024;
const maxRequestBytes = 8192;
const checkout = fileURLToPath(new URL("../../../", import.meta.url));
type LifecycleVerb = "status" | "start" | "stop";
let lifecyclePython: string | undefined;
class InvalidRequestError extends Error {}

type Connection = { port: number; token: string };

function tailnetAddress(value: string): boolean {
  const address = value
    .toLowerCase()
    .replace(/^::ffff:/, "")
    .replace(/^\[|\]$/g, "");
  if (isIP(address) === 4) {
    const parts = address.split(".").map(Number);
    return parts[0] === 100 && parts[1] >= 64 && parts[1] <= 127;
  }
  return isIP(address) === 6 && address.startsWith("fd7a:115c:a1e0:");
}

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
    host === "[::1]" ||
    tailnetAddress(host) ||
    manifest.devserver.allowedHosts.some(
      (allowed) => !allowed.startsWith(".") && allowed === host,
    )
  );
}

function localRequest(request: IncomingMessage): boolean {
  const address = request.socket.remoteAddress;
  if (
    !["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(address ?? "") &&
    !tailnetAddress(address ?? "")
  ) {
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
  try {
    JSON.parse(body);
  } catch {
    throw new InvalidRequestError("The monitor operation requires valid JSON.");
  }
  return body;
}

function allowedRoute(path: string, method: string): boolean {
  if (method === "GET") {
    return [
      "/health",
      "/jobs",
      "/search-activity",
      "/logs/json",
      "/lifecycle",
      "/service-state",
      "/runtime-observations",
      "/repositories",
      "/storage/survey",
      "/projects",
    ].includes(path);
  }
  const job = "/jobs/[a-zA-Z0-9_-]{1,128}";
  return (
    (method === "PUT" && new RegExp(`^${job}/desired-state$`).test(path)) ||
    (method === "POST" && new RegExp(`^${job}/retry$`).test(path)) ||
    (method === "POST" &&
      [
        "/lifecycle/start",
        "/lifecycle/stop",
        "/pause",
        "/resume",
        "/repositories/enroll",
        "/projects/evict",
      ].includes(path)) ||
    (method === "DELETE" && new RegExp(`^${job}$`).test(path))
  );
}

function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(
        ([key]) =>
          !["service_token", "token", "borrower_capability"].includes(key),
      )
      .map(([key, entry]) => [key, redact(entry)]),
  );
}

function timeout(path: string): number {
  if (path === "/lifecycle/start") return 900000;
  if (path === "/lifecycle/stop") return 120000;
  if (path === "/lifecycle" || path === "/storage/survey") return 30000;
  if (
    ["/pause", "/resume", "/repositories/enroll", "/projects/evict"].includes(
      path,
    )
  )
    return 120000;
  return 5000;
}

async function pythonRuntime(signal: AbortSignal): Promise<string> {
  if (lifecyclePython) return lifecyclePython;
  const interpreter =
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python";
  const toolsDirectory = await new Promise<string>((resolve) => {
    execFile(
      "uv",
      ["tool", "dir"],
      {
        cwd: checkout,
        encoding: "utf8",
        shell: false,
        windowsHide: true,
        timeout: 5000,
        maxBuffer: 8192,
        signal,
      },
      (error, stdout) => resolve(error ? "" : stdout.trim()),
    );
  });
  const candidates = [join(checkout, ".venv", interpreter)];
  if (isAbsolute(toolsDirectory) && !/[\r\n]/.test(toolsDirectory))
    candidates.unshift(join(toolsDirectory, "vaultspec-rag", interpreter));
  for (const candidate of candidates) {
    try {
      await access(candidate);
      lifecyclePython = candidate;
      return candidate;
    } catch {
      // An unenrolled tool can still use the checkout's Python environment.
    }
  }
  throw new Error("No local Python runtime is available for service controls.");
}

async function lifecycle(
  verb: LifecycleVerb,
  signal: AbortSignal,
): Promise<{ status: number; payload: Record<string, unknown> }> {
  const python = await pythonRuntime(signal);
  const { error, stdout } = await new Promise<{
    error: (Error & { code?: string | number; killed?: boolean }) | null;
    stdout: string;
  }>((resolve) => {
    execFile(
      python,
      ["-P", "-m", "vaultspec_rag", "server", verb, "--json"],
      {
        cwd: checkout,
        env: {
          ...process.env,
          PYTHONPATH: join(checkout, "src"),
          PYTHONUTF8: "1",
        },
        encoding: "utf8",
        shell: false,
        windowsHide: true,
        timeout: timeout(
          verb === "status" ? "/lifecycle" : `/lifecycle/${verb}`,
        ),
        maxBuffer: 1024 * 1024,
        signal,
      },
      (error, stdout) => resolve({ error, stdout }),
    );
  });
  if (error && (error.killed || typeof error.code !== "number")) throw error;
  const payload = object(JSON.parse(stdout));
  if (typeof payload.ok !== "boolean" || payload.command !== `service.${verb}`)
    throw new Error("The lifecycle owner returned an invalid response.");
  if (verb === "status") {
    if (error && ![3, 4, 5].includes(Number(error.code))) throw error;
    const state = object(payload.data).state;
    if (typeof state !== "string" || !state)
      throw new Error("The lifecycle owner returned no service state.");
    payload.state = state;
    return { status: 200, payload };
  }
  return { status: error || !payload.ok ? 503 : 200, payload };
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
  response.end(JSON.stringify(redact(body)));
}

async function forward(
  request: IncomingMessage,
  response: ServerResponse,
): Promise<void> {
  if (!localRequest(request)) {
    reply(response, 403, {
      ok: false,
      message:
        "The monitor accepts local and Tailscale clients at its declared host.",
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
    AbortSignal.timeout(timeout(route.pathname)),
  ]);
  try {
    const body =
      method === "PUT" || method === "POST"
        ? await requestBody(request, signal)
        : undefined;
    if (
      route.pathname === "/lifecycle" ||
      route.pathname.startsWith("/lifecycle/")
    ) {
      const parameters: unknown = body === undefined ? {} : JSON.parse(body);
      if (
        route.search ||
        parameters === null ||
        typeof parameters !== "object" ||
        Array.isArray(parameters) ||
        Object.keys(parameters).length !== 0
      ) {
        reply(response, 400, {
          ok: false,
          message:
            "Lifecycle controls accept an empty object and no parameters.",
        });
        return;
      }
      const verb: LifecycleVerb =
        route.pathname === "/lifecycle"
          ? "status"
          : route.pathname === "/lifecycle/start"
            ? "start"
            : "stop";
      const result = await lifecycle(verb, signal);
      reply(response, result.status, result.payload);
      return;
    }
    const local = await connection();
    const base = `http://127.0.0.1:${local.port}`;
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
    reply(response, result.status, payload);
  } catch (error) {
    if (error instanceof InvalidRequestError) {
      reply(response, 400, {
        ok: false,
        message: error.message,
      });
      return;
    }
    const message =
      error instanceof Error && error.message.startsWith("No local service")
        ? error.message
        : "The service is not responding. Check that it is running and try again.";
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
