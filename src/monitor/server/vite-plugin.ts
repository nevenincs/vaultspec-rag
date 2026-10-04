import type { Plugin } from "vite";
import { monitorMiddleware, monitorUpgrade } from "./local-service.ts";

export function localServicePlugin(): Plugin {
  return {
    name: "local-rag-monitor",
    configureServer(server) {
      server.httpServer?.prependListener("upgrade", monitorUpgrade);
      server.middlewares.use(monitorMiddleware);
    },
    configurePreviewServer(server) {
      server.httpServer.prependListener("upgrade", monitorUpgrade);
      server.middlewares.use(monitorMiddleware);
    },
  };
}
