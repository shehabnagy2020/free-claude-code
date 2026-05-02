# AGENTIC DIRECTIVE

> This is the primary agent directive file. CLAUDE.md references this file.

## CODING ENVIRONMENT

- Install astral uv using "curl -LsSf https://astral.sh/uv/install.sh | sh" if not already installed and if already installed then update it to the latest version
- Install Python 3.14 using `uv python install 3.14` if not already installed
- Run `npm install` at project root to install Node.js dependencies (context-mode sidecar).
- Always use `uv run` to run files instead of the global `python` command.
- Current uv ruff formatter is set to py314 which has supports multiple exception types without paranthesis (except TypeError, ValueError:)
- Read `.env.example` for environment variables.
- All CI checks must pass; failing checks block merge.
- Add tests for new changes (including edge cases), then run `uv run pytest`.
- Run checks in this order: `uv run ruff format`, `uv run ruff check`, `uv run ty check`, `uv run pytest`.
- Do not add `# type: ignore` or `# ty: ignore`; fix the underlying type issue.
- All 5 checks are enforced in `tests.yml` on push/merge.

## IDENTITY & CONTEXT

- You are an expert Software Architect and Systems Engineer.
- Goal: Zero-defect, root-cause-oriented engineering for bugs; test-driven engineering for new features. Think carefully; no need to rush.
- Code: Write the simplest code possible. Keep the codebase minimal and modular.
- **Deployment target**: Raspberry Pi 4 (8 GB). Prefer low-allocation hot paths; avoid unnecessary copies, byte-string encodes, or `copy.deepcopy` on per-event data.

## ARCHITECTURE PRINCIPLES (see PLAN.md)

- **Shared utilities**: Put shared Anthropic protocol logic in neutral `core/anthropic/` modules. Do not have one provider import from another provider's utils.
- **DRY**: Extract shared base classes to eliminate duplication. Prefer composition over copy-paste.
- **Encapsulation**: Use accessor methods for internal state (e.g. `set_current_task()`), not direct `_attribute` assignment from outside.
- **Provider-specific config**: Keep provider-specific fields (e.g. `nim_settings`) in provider constructors, not in the base `ProviderConfig`.
- **Dead code**: Remove unused code, legacy systems, and hardcoded values. Use settings/config instead of literals (e.g. `settings.provider_type` not `"nvidia_nim"`).
- **Performance**: Use list accumulation for strings (not `+=` in loops), cache env vars at init, prefer iterative over recursive when stack depth matters.
- **Platform-agnostic naming**: Use generic names (e.g. `PLATFORM_EDIT`) not platform-specific ones (e.g. `TELEGRAM_EDIT`) in shared code.
- **No type ignores**: Do not add `# type: ignore` or `# ty: ignore`. Fix the underlying type issue.
- **Complete migrations**: When moving modules, update imports to the new owner and remove old compatibility shims in the same change unless preserving a published interface is explicitly required.
- **Maximum Test Coverage**: There should be maximum test coverage for everything, preferably live smoke test coverage to catch bugs early
- **Catalog-driven provider sets**: Derive provider-type sets (e.g. `_OPENAI_CHAT_UPSTREAM_IDS`) from `config.provider_catalog.PROVIDER_CATALOG` using `d.transport_type`, never hardcode provider id strings in service logic.

## PROVIDER & CONNECTION STABILITY

- **Retryable network errors**: `httpx.ConnectError`, `ReadError`, `WriteError`, `RemoteProtocolError`, `TimeoutException`, and `openai.APIConnectionError` are all retryable. `GlobalRateLimiter.execute_with_retry` handles them with exponential backoff. `map_error` maps them to `APIError(503)`.
- **Mid-stream reconnect**: Both `OpenAIChatTransport` (`openai_compat.py`) and `AnthropicMessagesTransport` (`anthropic_messages.py`) retry the stream up to 2 times (`_MAX_STREAM_RETRIES = 2`) when a retryable network error occurs **before any content blocks have been emitted to the client**. Once content is flowing the error path is used instead (cannot unsend partial SSE).
- **keepalive_expiry**: All httpx clients use `keepalive_expiry=30.0` (via `httpx.Limits`) to prevent stale-connection drops on slow networks.
- **Error mapping**: Always call `map_error(e, rate_limiter=self._global_rate_limiter)` in streaming transports so reactive 429 handling is scoped to the correct provider.

## PERFORMANCE INVARIANTS (Pi 4)

- **SSE byte counting**: Do not call `.encode("utf-8")` on every SSE event string to count bytes. Use `len(event_str)` (char count) in `_format_event`.
- **tiktoken optional**: Import tiktoken inside `try/except` in both `core/anthropic/sse.py` and `core/anthropic/tokens.py`. All encode calls go through `_encode()` helper which falls back to `len(text) // 4` when the C extension is missing.
- **Shallow copy for SSE block state**: `content_block_start` payloads in `native_sse_block_policy.py` use a one-level manual dict copy instead of `copy.deepcopy` — block fields are flat strings/dicts.

## COGNITIVE WORKFLOW

1. **ANALYZE**: Read relevant files. Do not guess.
2. **PLAN**: Map out the logic. Identify root cause or required changes. Order changes by dependency.
3. **EXECUTE**: Fix the cause, not the symptom. Execute incrementally with clear commits.
4. **VERIFY**: Run ci checks and relevant smoke tests. Confirm the fix via logs or output.
5. **SPECIFICITY**: Do exactly as much as asked; nothing more, nothing less.
6. **PROPAGATION**: Changes impact multiple files; propagate updates correctly.

## SUMMARY STANDARDS

- Summaries must be technical and granular.
- Include: [Files Changed], [Logic Altered], [Verification Method], [Residual Risks] (if no residual risks then say none).

## TOOLS

- Prefer built-in tools (grep, read_file, etc.) over manual workflows. Check tool availability before use.

## WEB UI (`ui/`)

- Built with React + Vite + Tailwind. Source in `ui/src/`, built output in `ui/dist/` (served statically by FastAPI).
- **Always rebuild after editing UI source**: run `cd ui && npx vite build` on the deployment machine (Pi). PM2's `fcc-ui` process runs `vite build --watch` for auto-rebuild on that machine.
- **Auth**: Stateless HMAC-SHA256 tokens (`_TOKEN_SUFFIX = ":fcc-ui"`), no server-side session storage.
- **Database**: SQLite via `api/ui_db.py` — sessions, messages, history.
- **Model selector**: Fixed 3-tier (Opus/Sonnet/Haiku) with resolved provider display labels.
- **Streaming chat flow** (`api/ui_routes.py` → `ui/src/App.tsx`):
  1. Backend saves user message and **sets session title** (first turn only, `if not history`) _before_ the stream starts — no race.
  2. Frontend updates session title **optimistically in local state** the moment the user sends (no waiting for network).
  3. Frontend shows streamed text via `StreamingBubble`; on `onDone` it appends an optimistic `Message` immediately, clears streaming state, then background-syncs with DB (retries at 100/300/600 ms until last message has `role=="assistant"`).
  4. `loadSessions()` is called once after the DB sync confirms the assistant message is persisted.
- **No fixed-delay polling for titles**: title is set server-side before the HTTP response body starts, and mirrored client-side optimistically — never poll for it.
- **Race-free DB sync**: `onDone` never clears streaming state before the canonical messages are fetched; optimistic message prevents blank-screen flash.
- **`ui/src/lib/api.ts`**: all HTTP calls. `streamChat` returns an `AbortController`; retries connection errors up to 2× with exponential backoff.

### Tavily Web Search Integration (UI)

- **Proactive search**: Detects real-time queries via `_REALTIME_KEYWORDS` (time refs, weather, news, finance, sports, tech, search intent).
- **Context-aware queries**: For follow-ups like "and this week?", prepends last user turn from history for topic/location context.
- **System prompt injection**: Tavily results injected as `_tavily_system` before LLM call — no tool round-trip, works with any model.
- **Enrichment** (`api/web_tools/enrichment.py`): Auto-fills empty `WebSearch`/`WebFetch` tool_result blocks from Claude Code with Tavily data.
- **Module-level caches**: `_REALTIME_KEYWORDS` frozenset built once at import; Tavily client reuses httpx connections.
- **Keywords**: `today`, `weather`, `news`, `price`, `score`, `trending`, `search`, `who is`, `what is`, etc. (see `_REALTIME_KEYWORDS` in `api/ui_routes.py`).

### Global Memory (UI)

- **Purpose**: Persist user facts across all chat sessions (e.g. "my name is Shehab", "my age is 28").
- **Storage**: SQLite `global_memory` table in `ui_chat.db` — key/value with upsert.
- **Real-time extraction** (`api/ui_routes.py`): When a user message contains memory keywords ("remember", "keep in mind", "note", "don't forget", "make sure", "save", "write down"), the fact is extracted via regex and immediately upserted to the DB — no waiting for background summary.
- **System prompt injection**: Global memory is **always** injected into the system prompt on every turn. On follow-up turns, session summary is also included. This ensures facts persist across all sessions immediately.
- **Background summary** (`api/summary.py`): After each chat turn, a summary is generated and `REMEMBER:`/`KEEP:`/`NOTE:`/`DON'T FORGET:`/`SAVE:` tagged items are extracted to global memory as a secondary path. The summary also prepends current global memory so it stays embedded in session context.
- **Dedup**: `_extract_memory_from_text` filters filler words ("that", "this", "it") and deduplicates overlapping captures (e.g. "save my phone number" vs "my phone number" — keeps shorter).

## CONTEXT-MODE INTEGRATION

- **Sidecar process**: `api/runtime.py` launches `npx -y context-mode` as a subprocess on `AppRuntime.startup()`, kills on `shutdown()` + `atexit` safety net. Log: `Context-mode sidecar started (pid=...)`.
- **System prompt nudge**: `core/nudge.py` contains a ~115-token sandbox routing nudge. Injected into every request's system prompt via `_inject_context_mode_system_prompt()` in `api/services.py` (follows the `inject_web_search_system_prompt` pattern). Idempotent (skips if `"CONTEXT-MODE SANDBOX"` already present). Log: `[5c] Injected context-mode sandbox nudge (~115 tokens)`.
- **Output chatter stripping**: `core/chatter.py` provides `ChatterStripper` — a sentence-based filter that strips local-model filler prefixes ("Certainly! I can help with that.", "Of course! Let me assist...", etc.) from the first text block of responses. Applied via `_chatter_stripped_stream()` wrapper in `api/services.py` which wraps **all** provider SSE streams (both openai_chat and anthropic_messages transports). Colon-aware splitting preserves content after colons. Log: `CHATTER_STRIP: removed N chars from '...' → '...'`.
- **No provider-specific stripping**: Chatter stripping is unified at the services layer, not in individual provider transports. The OpenAI-compat path (`providers/openai_compat.py`) does NOT have its own ChatterStripper.
- **package.json**: Root-level `package.json` declares `context-mode` as an npm dependency. Run `npm install` before starting the proxy.
- **Nudge + Tavily coexistence**: The web search system prompt instruction (`[5b]`) and context-mode nudge (`[5c]`) are both appended to the system prompt. The nudge clarifies that the proxy's `web_search`/`web_fetch` tools (Tavily-handled) are fine to use — only raw `WebFetch` (which dumps HTML into context) is blocked.
- **Pipeline order**: REQUEST → ROUTED → WEB_TOOLS → OPTIMIZATION → STRIP_SERVER_TOOLS → INJECT_WEB_SEARCH → INJECT_CONTEXT_MODE_NUDGE → FORWARD → STREAM (with chatter stripping).

## IMAGE SUPPORT

- Discord and Telegram platforms support image attachments (PNG, JPEG, GIF, WebP)
- Images are extracted, base64-encoded, and sent directly to the proxy API via `POST /v1/messages`
- Image messages bypass the Claude CLI subprocess (images cannot be passed via `-p` command line flag)
- OpenAI-compatible providers (NVIDIA NIM) receive images as `image_url` format; native Anthropic providers receive standard Anthropic image blocks
- Test image handling with edge cases: empty captions, multiple images, unsupported formats
- Key modules: `messaging/models.py` (ImageAttachment), `messaging/handler.py` (\_send_image_message_to_api), `messaging/platforms/discord.py` and `telegram.py` (image extraction), `core/anthropic/conversion.py` (OpenAI image_url conversion)
