import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiHost = process.env.COURSE_NAVIGATOR_API_HOST ?? "127.0.0.1";
const apiPort = process.env.COURSE_NAVIGATOR_API_PORT ?? "18000";

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  server: {
    port: Number(process.env.COURSE_NAVIGATOR_WEB_PORT ?? 15173),
    // The launcher waits on this exact port; never drift to another one.
    strictPort: true,
    proxy: {
      "/api": `http://${apiHost}:${apiPort}`,
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
