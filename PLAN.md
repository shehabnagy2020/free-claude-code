# PLAN: Context-Mode Hybrid Integration

## Goal

Implement a "Zero-Config" optimization layer that runs `context-mode` as a sidecar and injects efficient routing rules into every LLM request.

## Tasks

- [x] **Phase 1: Dependency Setup**
  - Create `package.json` with `context-mode`.
  - Update install instructions (README.md) to include `npm install`.
- [x] **Phase 2: Sidecar Process**
  - Add sidecar launch/kill to `api/runtime.py` (`_start_context_mode_sidecar`, `_stop_context_mode_sidecar`).
  - Launch `npx -y context-mode` on `AppRuntime.startup()`.
  - Kill on `AppRuntime.shutdown()` + `atexit` safety net.
- [x] **Phase 3: System Prompt Injection**
  - Create `core/nudge.py` with the condensed context-mode routing nudge (~115 tokens).
  - Add `_inject_context_mode_system_prompt()` to `api/services.py`, following the `inject_web_search_system_prompt` pattern.
  - Called on every request in the pipeline (after web search injection).
- [x] **Phase 4: Output Cleaning**
  - Create `core/chatter.py` with `ChatterStripper` — sentence-based filler detection.
  - Strips known chatter prefixes ("Certainly!", "Of course!", "Let me help", etc.) from the first text block.
  - Colon-aware splitting preserves content after colons in filler sentences.
  - Integrated into `providers/openai_compat.py` text delta path.