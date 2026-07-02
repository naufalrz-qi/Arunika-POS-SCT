import { resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

const INPUT_DIR = "./frontend";
const OUTPUT_DIR = "./frontend/dist";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [vue(), tailwindcss()],
    resolve: {
      alias: {
        "@": resolve(INPUT_DIR),
      },
    },
    root: resolve(INPUT_DIR),
    base: "/static/",
    server: {
      host: "0.0.0.0",
      port: Number(env.DJANGO_VITE_DEV_SERVER_PORT) || 5173,
      watch: { usePolling: true },
      allowedHosts: [".echidna-carob.ts.net", "localhost", "127.0.0.1"],
      // Django's dev_server_host is fixed to "localhost" in settings.py, so the
      // page (served from whatever hostname you browse to) always requests
      // scripts from http://localhost:5173 — a different origin. Vite's dev
      // server otherwise replies without CORS headers and the browser blocks it.
      cors: true,
    },
    build: {
      manifest: "manifest.json",
      emptyOutDir: true,
      outDir: resolve(OUTPUT_DIR),
      rollupOptions: {
        input: {
          main: resolve(INPUT_DIR, "js/main.js"),
        },
      },
    },
  };
});
