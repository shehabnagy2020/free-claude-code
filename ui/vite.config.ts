import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Plugin to copy static PWA files after build
const copyPWAFiles = () => ({
  name: "copy-pwa-files",
  closeBundle() {
    const publicDir = path.resolve(__dirname, "public");
    const distDir = path.resolve(__dirname, "dist");
    // Copy manifest.json
    const manifestSrc = path.join(publicDir, "manifest.json");
    if (fs.existsSync(manifestSrc)) {
      fs.copyFileSync(manifestSrc, path.join(distDir, "manifest.json"));
    }
    // Copy sw.js
    const swSrc = path.join(publicDir, "sw.js");
    if (fs.existsSync(swSrc)) {
      fs.copyFileSync(swSrc, path.join(distDir, "sw.js"));
    }
  },
});

export default defineConfig({
  plugins: [
    react(),
    copyPWAFiles(),
    VitePWA({
      registerType: "autoUpdate",
      workbox: {
        // Disable all caching - network only
        runtimeCaching: [],
        navigateFallback: undefined,
        cleanupOutdatedCaches: true,
        globPatterns: [], // Don't precache anything
      },
      manifest: {
        name: "Claude Code",
        short_name: "Claude Code",
        description: "Claude Code AI Assistant",
        start_url: "/ui/",
        scope: "/ui/",
        display: "standalone",
        background_color: "#0d0f14",
        theme_color: "#0d0f14",
        icons: [
          {
            src: "/ui/icon.svg",
            sizes: "any",
            type: "image/svg+xml",
          },
        ],
      },
    }),
  ],
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
