import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Assets will be under /ui/assets/ when served by FastAPI
  base: "/ui/",
  server: {
    // Dev-mode proxy: forward /ui/api/* and /v1/* to the FastAPI backend
    proxy: {
      "/ui/api": {
        target: "http://localhost:8082",
        changeOrigin: true,
      },
      "/v1": {
        target: "http://localhost:8082",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom"],
          markdown: ["react-markdown", "remark-gfm", "remark-breaks"],
          highlight: ["react-syntax-highlighter"],
        },
      },
    },
  },
});
