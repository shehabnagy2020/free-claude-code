const path = require("path");

module.exports = {
  apps: [
    {
      name: "fcc",
      script: "uv",
      args: "run free-claude-code",
      cwd: __dirname,
      watch: ["api", "cli", "config", "core", "messaging", "providers"],
      watch_options: {
        persistent: true,
        ignoreInitial: true,
      },
      ignore_watch: [
        "**/__pycache__",
        "**/*.pyc",
        "**/*.pyo",
        "**/.pytest_cache",
        "**/node_modules",
      ],
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 10000,
      max_memory_restart: "500M",
      node_args: undefined,
      env: {
        PYTHONUNBUFFERED: "1",
        UVICORN_LIMIT_CONCURRENCY: 50,
      },
    },
    {
      name: "fcc-ui",
      script: "npx",
      args: "vite build --watch",
      cwd: path.join(__dirname, "ui"),
      watch: false, // Vite's own watcher handles src changes
      autorestart: false, // Vite watch mode is long-running; don't restart on exit
      max_memory_restart: "512M",
      env: {
        NODE_ENV: "production",
      },
    },
  ],
};
