import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import manifest from "./package.json" with { type: "json" };

const { devserver, portless } = manifest;

export default defineConfig({
  root: fileURLToPath(new URL("./src/monitor", import.meta.url)),
  base: "./",
  plugins: [react()],
  server: {
    host: devserver.host,
    port: portless.appPort,
    strictPort: true,
    allowedHosts: devserver.allowedHosts,
  },
  preview: {
    host: devserver.host,
    port: devserver.services.preview.port,
    strictPort: true,
    allowedHosts: devserver.allowedHosts,
  },
});
