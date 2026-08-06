import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Same-origin by proxy: the browser only ever talks to localhost:5173, so there
    // is no CORS involved at all. 127.0.0.1 rather than "localhost" because Windows
    // resolves localhost to ::1 first, which Flask is not listening on.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
    },
  },
  build: {
    // Flask serves this directory in production — also same-origin, no proxy needed.
    outDir: "dist",
  },
});
