import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:14001",
      "/import-cookies": "http://127.0.0.1:14001",
      "/xhs": "http://127.0.0.1:14001",
      "/x": "http://127.0.0.1:14001",
      "/pixiv": "http://127.0.0.1:14001",
      "/douyin": "http://127.0.0.1:14001"
    }
  }
});
