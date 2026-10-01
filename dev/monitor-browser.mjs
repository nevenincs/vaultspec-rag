// Render the production monitor in an installed browser against real local routes.
import { spawn } from "node:child_process";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { setTimeout as delay } from "node:timers/promises";
import { createServer } from "vite";
import config from "../vite.config.ts";

const [executable, directory] = process.argv.slice(2);
if (!executable || !directory)
  throw new Error(
    "Pass the installed browser and an isolated profile directory.",
  );
await mkdir(directory, { recursive: true });
const server = await createServer({
  ...config,
  configFile: false,
  cacheDir: join(directory, "vite-cache"),
  logLevel: "error",
  server: { ...config.server, port: 0, strictPort: true, host: "127.0.0.1" },
});
let browser;
let socket;
const pending = new Map();
const errors = [];
const network = [];
let backgroundTarget;
let sequence = 0;
const send = (method, params = {}, timeout = 10000) =>
  new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Browser command timed out: ${method}`));
    }, timeout);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression, timeout) => {
  const result = await send(
    "Runtime.evaluate",
    { expression, returnByValue: true, awaitPromise: true },
    timeout,
  );
  if (result.exceptionDetails)
    throw new Error(
      result.exceptionDetails.exception?.description ??
        result.exceptionDetails.text,
    );
  return result.result.value;
};
try {
  await server.listen();
  const address = server.httpServer.address();
  const url = `http://127.0.0.1:${address.port}`;
  browser = spawn(
    executable,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      "--remote-debugging-port=0",
      `--user-data-dir=${directory}`,
      "about:blank",
    ],
    { windowsHide: true, stdio: ["ignore", "ignore", "inherit"] },
  );
  let debuggerPort;
  const deadline = Date.now() + 45000;
  while (!debuggerPort && Date.now() < deadline) {
    try {
      debuggerPort = Number(
        (await readFile(join(directory, "DevToolsActivePort"), "utf8")).split(
          "\n",
        )[0],
      );
    } catch {
      await delay(50);
    }
  }
  if (!debuggerPort)
    throw new Error("The installed browser did not open its debugger.");
  const targets = await (
    await fetch(`http://127.0.0.1:${debuggerPort}/json/list`)
  ).json();
  socket = new WebSocket(
    targets.find((target) => target.type === "page").webSocketDebuggerUrl,
  );
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const reply = pending.get(message.id);
      if (!reply) return;
      pending.delete(message.id);
      clearTimeout(reply.timer);
      if (message.error) reply.reject(new Error(message.error.message));
      else reply.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown")
      errors.push(message.params.exceptionDetails);
    else if (
      message.method === "Network.requestWillBeSent" &&
      message.params.request.url.includes("/api/monitor/")
    )
      network.push(message.params.request.url);
    else if (
      message.method === "Network.loadingFailed" &&
      !message.params.canceled
    )
      errors.push(message.params);
  });
  socket.addEventListener("close", () => {
    for (const reply of pending.values()) {
      clearTimeout(reply.timer);
      reply.reject(new Error("The browser closed."));
    }
    pending.clear();
  });
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Network.enable");
  await send("Page.navigate", { url });
  process.stdout.write(`${JSON.stringify({ ready: true, url })}\n`);
  const input = createInterface({ input: process.stdin });
  for await (const line of input) {
    try {
      const command = JSON.parse(line);
      let value;
      if (command.operation === "evaluate")
        value = await evaluate(command.expression);
      else if (command.operation === "wait") {
        const until = Date.now() + (command.timeout ?? 30000);
        while (Date.now() < until) {
          value = await evaluate(command.expression, until - Date.now());
          if (value) break;
          await delay(50);
        }
        if (!value)
          throw new Error(`Condition not reached: ${command.expression}`);
      } else if (command.operation === "resize") {
        value = await send("Emulation.setDeviceMetricsOverride", {
          width: command.width,
          height: command.height,
          deviceScaleFactor: 1,
          mobile: false,
        });
      } else if (command.operation === "screenshot") {
        const capture = await send("Page.captureScreenshot", {
          format: "png",
          captureBeyondViewport: false,
        });
        await writeFile(command.path, Buffer.from(capture.data, "base64"));
        value = command.path;
      } else if (command.operation === "memory") {
        // Let pending layout/tooltip callbacks release their temporary DOM refs.
        await evaluate(
          "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))",
        );
        await delay(500);
        await send("HeapProfiler.collectGarbage");
        value = await send("Memory.getDOMCounters");
      } else if (command.operation === "background") {
        if (command.hidden) {
          const target = await send("Target.createTarget", {
            url: "about:blank",
          });
          backgroundTarget = target.targetId;
          await send("Target.activateTarget", { targetId: backgroundTarget });
        } else {
          if (backgroundTarget)
            await send("Target.closeTarget", { targetId: backgroundTarget });
          backgroundTarget = undefined;
          await send("Page.bringToFront");
        }
      } else if (command.operation === "evidence") value = { errors, network };
      else if (command.operation === "close") {
        input.close();
        break;
      } else throw new Error("Unknown browser check operation.");
      process.stdout.write(`${JSON.stringify({ ok: true, value })}\n`);
    } catch (error) {
      process.stdout.write(
        `${JSON.stringify({ ok: false, message: error.message })}\n`,
      );
    }
  }
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    await send("Browser.close").catch(() => {});
    socket.close();
  }
  browser?.kill();
  await server.close();
  process.stdin.destroy();
}
