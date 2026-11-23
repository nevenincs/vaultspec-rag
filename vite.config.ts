import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import manifest from "./package.json" with { type: "json" };
import { localServicePlugin } from "./src/monitor/server/vite-plugin.ts";

const { monitor } = manifest;

export default defineConfig({
  root: fileURLToPath(new URL("./src/monitor", import.meta.url)),
  base: "./",
  plugins: [react(), localServicePlugin()],
  css: {
    preprocessorOptions: {
      // Carbon's own stylesheets use Sass syntax that Sass now deprecates; the
      // warnings are unfixable here, so silence them for dependencies only and
      // keep reporting deprecations in this project's stylesheets.
      scss: { quietDeps: true },
    },
  },
  server: {
    host: monitor.host,
    port: monitor.port,
    strictPort: true,
    allowedHosts: monitor.allowedHosts,
  },
  preview: {
    host: monitor.host,
    port: monitor.previewPort,
    strictPort: true,
    allowedHosts: monitor.allowedHosts,
  },
});
