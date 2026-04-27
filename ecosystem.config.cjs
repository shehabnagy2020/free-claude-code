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
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      max_memory_restart: "500M",
      node_args: undefined,
      env: {
        PYTHONUNBUFFERED: "1",
        UVICORN_LIMIT_CONCURRENCY: 50,
      },
    },
  ],
};