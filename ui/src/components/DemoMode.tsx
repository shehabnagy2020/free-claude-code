import { useState, useCallback } from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";
import ChatView from "./ChatView";
import type {
  Session,
  Message,
  ModelOption,
  MemoryEntry,
} from "../types";

// ── Mock data ──────────────────────────────────────────────────────────────────

const NOW = new Date().toISOString();

const DEMO_MODELS: ModelOption[] = [
  {
    label: "Claude Opus 4",
    claude_model: "claude-opus-4-20250514",
    provider_display: "Anthropic",
    is_default: true,
  },
  {
    label: "Claude Sonnet 4",
    claude_model: "claude-sonnet-4-20250514",
    provider_display: "Anthropic",
    is_default: false,
  },
  {
    label: "Claude Haiku 4",
    claude_model: "claude-haiku-4-20250514",
    provider_display: "Anthropic",
    is_default: false,
  },
];

const DEMO_MEMORY: MemoryEntry[] = [
  {
    key: "theme_preference",
    value: "Prefers dark mode themes in all tools",
    updated_at: NOW,
  },
  {
    key: "current_project",
    value: "Working on a Python async web service using FastAPI",
    updated_at: NOW,
  },
  {
    key: "editor",
    value: "Uses VS Code with Vim keybindings",
    updated_at: NOW,
  },
];

const DEMO_SESSIONS: Session[] = [
  {
    id: "demo-1",
    title: "Python async patterns",
    model: "claude-opus-4-20250514",
    created_at: new Date(Date.now() - 3600_000).toISOString(),
    updated_at: new Date(Date.now() - 600_000).toISOString(),
    message_count: 4,
    summary: "Discussed asyncio.gather vs TaskGroup for concurrent HTTP requests. REMEMBER: User prefers modern Python 3.11+ patterns.",
  },
  {
    id: "demo-2",
    title: "Docker compose best practices",
    model: "claude-sonnet-4-20250514",
    created_at: new Date(Date.now() - 86400_000).toISOString(),
    updated_at: new Date(Date.now() - 43200_000).toISOString(),
    message_count: 6,
    summary: "Multi-stage builds, health checks, and named volumes for a FastAPI + Postgres stack.",
  },
  {
    id: "demo-3",
    title: "CSS Grid vs Flexbox",
    model: "claude-haiku-4-20250514",
    created_at: new Date(Date.now() - 172800_000).toISOString(),
    updated_at: new Date(Date.now() - 172800_000).toISOString(),
    message_count: 2,
    summary: null,
  },
];

const DEMO_MESSAGES: Record<string, Message[]> = {
  "demo-1": [
    {
      id: "m1",
      session_id: "demo-1",
      role: "user",
      content: "What's the difference between asyncio.gather and asyncio.TaskGroup? When should I use each?",
      created_at: new Date(Date.now() - 3600_000).toISOString(),
    },
    {
      id: "m2",
      session_id: "demo-1",
      role: "assistant",
      content: `Both \`asyncio.gather\` and \`asyncio.TaskGroup\` run coroutines concurrently, but they have different error-handling semantics and ergonomics.

## \`asyncio.gather\`

- Introduced in Python 3.4
- Returns results in the **same order** as the input coroutines
- If one task raises, the exception propagates immediately, but **other tasks continue running** unless you handle it
- Use \`return_exceptions=True\` to collect exceptions as results instead of propagating

\`\`\`python
results = await asyncio.gather(
    fetch_user(user_id),
    fetch_orders(user_id),
    fetch_settings(user_id),
)
# results = [user_data, orders_data, settings_data]
\`\`\`

## \`asyncio.TaskGroup\`

- Introduced in Python 3.11
- Uses \`async with\` — cleaner syntax
- If **any** task raises, all other tasks are **automatically cancelled**, and the exception propagates after the group exits
- This "structured concurrency" pattern prevents orphaned tasks

\`\`\`python
async with asyncio.TaskGroup() as tg:
    user_task = tg.create_task(fetch_user(user_id))
    orders_task = tg.create_task(fetch_orders(user_id))
    settings_task = tg.create_task(fetch_settings(user_id))
# All results available after the block
user = user_task.result()
orders = orders_task.result()
\`\`\`

## When to use which

| Scenario | Recommendation |
|---|---|
| Independent fetches where you want all results even if one fails | \`gather(return_exceptions=True)\` |
| Related operations where partial failure means the whole batch is invalid | \`TaskGroup\` |
| New code targeting Python 3.11+ | **TaskGroup** — it's the safer default |
| Need to preserve result ordering from unordered inputs | \`gather\` |

**TL;DR**: For new code, default to \`TaskGroup\`. Use \`gather\` only when you need \`return_exceptions=True\` or are on Python <3.11.`,
      created_at: new Date(Date.now() - 3500_000).toISOString(),
    },
    {
      id: "m3",
      session_id: "demo-1",
      role: "user",
      content: "Can you show me a TaskGroup example that handles a realistic error scenario?",
      created_at: new Date(Date.now() - 1800_000).toISOString(),
    },
    {
      id: "m4",
      session_id: "demo-1",
      role: "assistant",
      content: `Here's a practical example — fetching data from multiple APIs where one might fail:

\`\`\`python
import asyncio
from httpx import AsyncClient, HTTPStatusError

async def fetch_service(client: AsyncClient, name: str, url: str) -> dict:
    resp = await client.get(url)
    resp.raise_for_status()
    return {"service": name, "data": resp.json()}

async def fetch_all_services():
    async with AsyncClient() as client:
        try:
            async with asyncio.TaskGroup() as tg:
                auth = tg.create_task(
                    fetch_service(client, "auth", "https://api.example.com/auth")
                )
                billing = tg.create_task(
                    fetch_service(client, "billing", "https://api.example.com/billing")
                )
                profile = tg.create_task(
                    fetch_service(client, "profile", "https://api.example.com/profile")
                )
        except ExceptionGroup as eg:
            # One or more tasks failed — all others were auto-cancelled
            for exc in eg.exceptions:
                if isinstance(exc, HTTPStatusError):
                    print(f"HTTP error: {exc.response.status_code}")
                else:
                    print(f"Unexpected: {exc!r}")
            raise  # re-raise to signal caller

        # If we reach here, all three succeeded
        return {
            "auth": auth.result(),
            "billing": billing.result(),
            "profile": profile.result(),
        }
\`\`\`

The key insight: if **billing** returns a 500 error, both **auth** and **profile** tasks get cancelled automatically. You don't end up in a half-loaded state. This is why \`TaskGroup\` is the safer choice for related operations — it guarantees atomicity at the concurrency level.`,
      created_at: new Date(Date.now() - 1700_000).toISOString(),
    },
  ],
  "demo-2": [
    {
      id: "m5",
      session_id: "demo-2",
      role: "user",
      content: "What are some Docker Compose best practices for a production FastAPI + Postgres setup?",
      created_at: new Date(Date.now() - 86400_000).toISOString(),
    },
    {
      id: "m6",
      session_id: "demo-2",
      role: "assistant",
      content: `Here are the key practices I'd recommend:

### 1. Multi-stage builds for the API image

\`\`\`dockerfile
# Build stage
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
\`\`\`

This keeps the final image small — no build tools or pip cache.

### 2. Named volumes for Postgres data

\`\`\`yaml
volumes:
  pgdata:

services:
  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
\`\`\`

### 3. Health checks + \`depends_on\` with condition

\`\`\`yaml
  api:
    build: .
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"
\`\`\`

This ensures the API doesn't start until Postgres is actually ready — not just until the container is running.

### 4. Use Docker secrets, not env vars for sensitive data

\`\`\`yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt
\`\`\`

Secrets are mounted as tmpfs, never written to disk, and don't appear in \`docker inspect\`.

### 5. Resource limits

\`\`\`yaml
  api:
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"
\`\`\`

Prevents a runaway process from consuming the entire host.`,
      created_at: new Date(Date.now() - 86000_000).toISOString(),
    },
    {
      id: "m7",
      session_id: "demo-2",
      role: "user",
      content: "How do I handle database migrations in this setup?",
      created_at: new Date(Date.now() - 43200_000).toISOString(),
    },
    {
      id: "m8",
      session_id: "demo-2",
      role: "assistant",
      content: `The cleanest approach is a one-off migration container that runs before the API starts:

\`\`\`yaml
  migrate:
    build: .
    command: ["alembic", "upgrade", "head"]
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:\${DB_PASSWORD}@db:5432/appdb

  api:
    build: .
    depends_on:
      migrate:
        condition: service_completed_successfully
\`\`\`

The \`service_completed_successfully\` condition means the API waits until migrations finish **with exit code 0**. If migrations fail, the API never starts — which is exactly what you want.

**Tip**: If you use \`service_completed_successfully\`, make sure your migration tool exits with a non-zero code on failure. Alembic does this by default.

For development, you can also add a \`profile\` so migrations only run when explicitly requested:

\`\`\`yaml
  migrate:
    build: .
    profiles: ["migrate"]
    command: ["alembic", "upgrade", "head"]
\`\`\`

Then run with \`docker compose --profile migrate up migrate\` instead of it running every time.`,
      created_at: new Date(Date.now() - 43000_000).toISOString(),
    },
  ],
  "demo-3": [
    {
      id: "m9",
      session_id: "demo-3",
      role: "user",
      content: "When should I use CSS Grid vs Flexbox?",
      created_at: new Date(Date.now() - 172800_000).toISOString(),
    },
    {
      id: "m10",
      session_id: "demo-3",
      role: "assistant",
      content: `**Short answer**: Use Grid for 2D layouts, Flexbox for 1D layouts.

## Grid is for rows AND columns

Grid excels when you need to control both axes simultaneously:

\`\`\`css
.dashboard {
  display: grid;
  grid-template-columns: 250px 1fr;
  grid-template-rows: auto 1fr auto;
  grid-template-areas:
    "sidebar header"
    "sidebar main"
    "sidebar footer";
  height: 100vh;
}
\`\`\`

## Flexbox is for a single direction

Flexbox shines when you're distributing space along one axis:

\`\`\`css
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-row {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}
\`\`\`

## Quick decision guide

- **Align items in a row or column?** → Flexbox
- **Create a full page layout with rows and columns?** → Grid
- **Center something?** → Flexbox (3 lines, always works)
- **Equal-height columns?** → Grid (or Flexbox with \`align-items: stretch\`)
- **Reorder items?** → Either works, Flexbox \`order\` is simpler

They compose perfectly — use Grid for the page shell, Flexbox inside each region. You don't have to pick just one.`,
      created_at: new Date(Date.now() - 172700_000).toISOString(),
    },
  ],
};

const DEMO_SUMMARIES: Record<string, string> = {
  "demo-1":
    "Discussed asyncio.gather vs TaskGroup for concurrent HTTP requests. REMEMBER: User prefers modern Python 3.11+ patterns.",
  "demo-2":
    "Multi-stage builds, health checks, named volumes, and Alembic migrations for a FastAPI + Postgres stack.",
};

// ── Toast ──────────────────────────────────────────────────────────────────────

function Toast({ message }: { message: string }) {
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-xl border border-white/10 bg-[#1a1d25] px-4 py-2.5 text-sm text-surface-300 shadow-2xl shadow-black/50 animate-fade-in">
      {message}
    </div>
  );
}

// ── Component ──────────────────────────────────────────────────────────────────

interface Props {
  onExit: () => void;
}

export default function DemoMode({ onExit }: Props) {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    "demo-1"
  );
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ModelOption>(
    DEMO_MODELS[0]
  );
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2000);
  }, []);

  const handleSelectModel = useCallback(
    (m: ModelOption) => {
      setSelectedModel(m);
      showToast("Model selection is cosmetic in demo mode");
    },
    [showToast]
  );

  const activeSession =
    DEMO_SESSIONS.find((s) => s.id === activeSessionId) ?? null;
  const messages = activeSessionId
    ? (DEMO_MESSAGES[activeSessionId] ?? [])
    : [];
  const sessionSummary = activeSessionId
    ? (DEMO_SUMMARIES[activeSessionId] ?? null)
    : null;

  // No-op handlers with toast
  const handleNewChat = useCallback(
    () => showToast("This is a demo — sign in to create new chats"),
    [showToast]
  );
  const handleSend = useCallback(
    () => showToast("This is a demo — sign in to send messages"),
    [showToast]
  );
  const handleDeleteSession = useCallback(
    () => showToast("This is a demo — sign in to manage sessions"),
    [showToast]
  );
  const handleRenameSession = useCallback(
    () => showToast("This is a demo — sign in to manage sessions"),
    [showToast]
  );
  const handleDeleteMemory = useCallback(
    () => showToast("This is a demo — sign in to manage memory"),
    [showToast]
  );
  const handleResend = useCallback(
    () => showToast("This is a demo — sign in to resend messages"),
    [showToast]
  );

  return (
    <div className="flex h-full overflow-hidden bg-[#0d0f14]">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/60 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={[
          "fixed inset-y-0 left-0 z-30 w-72 flex-shrink-0 transform transition-transform duration-200",
          "md:relative md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
      >
        <Sidebar
          sessions={DEMO_SESSIONS}
          activeSessionId={activeSessionId}
          memory={DEMO_MEMORY}
          onSelectSession={setActiveSessionId}
          onNewChat={handleNewChat}
          onDeleteSession={handleDeleteSession}
          onRenameSession={handleRenameSession}
          onDeleteMemory={handleDeleteMemory}
          onClose={() => setSidebarOpen(false)}
        />
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        <Header
          session={activeSession}
          models={DEMO_MODELS}
          selectedModel={selectedModel}
          onSelectModel={handleSelectModel}
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
          onLogout={onExit}
          onNewChat={handleNewChat}
        />

        <main className="flex flex-1 flex-col overflow-hidden">
          <ChatView
            messages={messages}
            streamingText={null}
            isLoading={false}
            isStreaming={false}
            error={null}
            hasSession={activeSessionId !== null}
            models={DEMO_MODELS}
            sessionSummary={sessionSummary}
            onSend={handleSend}
            onResend={handleResend}
            onStop={() => {}}
            onNewChat={handleNewChat}
          />
        </main>
      </div>

      {/* Toast */}
      {toast && <Toast message={toast} />}
    </div>
  );
}