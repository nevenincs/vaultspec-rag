import type { Logger, Plugin, PreviewServer } from "vite";
import {
  monitorAccess,
  monitorMiddleware,
  monitorUpgrade,
} from "./local-service.ts";

function announce(server: PreviewServer["httpServer"], logger: Logger): void {
  server.once("listening", () => {
    const address = server.address();
    if (address && typeof address === "object")
      logger.info(`  ➜  Monitor: ${monitorAccess(address.port)}`);
  });
}

export function localServicePlugin(): Plugin {
  return {
    name: "local-rag-monitor",
    configureServer(server) {
      server.httpServer?.prependListener("upgrade", monitorUpgrade);
      if (server.httpServer) announce(server.httpServer, server.config.logger);
      server.middlewares.use(monitorMiddleware);
    },
    configurePreviewServer(server) {
      server.httpServer.prependListener("upgrade", monitorUpgrade);
      announce(server.httpServer, server.config.logger);
      server.middlewares.use(monitorMiddleware);
    },
  };
}
