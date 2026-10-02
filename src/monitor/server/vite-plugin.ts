import type { Plugin } from "vite";
import { monitorMiddleware } from "./local-service.ts";

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
