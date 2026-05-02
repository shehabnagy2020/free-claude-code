"""System prompt injection for context-mode MCP sandbox routing."""

CONTEXT_MODE_NUDGE = """

# CONTEXT-MODE SANDBOX (MANDATORY)

## Think in Code
Analyze/count/filter/parse data by writing code via `ctx_execute(language, code)`.
Only stdout enters context. Never Read() files for analysis — use `ctx_execute_file` instead.
console.log() the result. One script replaces ten tool calls.

## Blocked
curl, wget, inline HTTP — blocked. Use `ctx_fetch_and_index` then `ctx_search`.
Raw WebFetch (dumps HTML into context) — blocked. The proxy's `web_search`/`web_fetch` tools are fine (Tavily handles them).

## Tool Routing
- Bash only for: git, mkdir, rm, mv, cd, ls, npm/pip install. All else → `ctx_batch_execute` or `ctx_execute`.
- Grep with large output → `ctx_execute("shell", "grep ...")` in sandbox.
- Gather info → `ctx_batch_execute(commands, queries)` — one call replaces many.

## Output Style
Terse. No pleasantries. Fragments OK. Pattern: [action] [result].
Write artifacts to files, return path + 1-line summary.
"""

# Summarized nudge for bandwidth-constrained deployments (~35 tokens)
# Written as imperative rules without section headers to avoid model mimicry
CONTEXT_MODE_NUDGE_SHORT = """
Use `ctx_execute()` or `ctx_execute_file()` for data and file analysis — never curl/wget/inline HTTP.
For web: `ctx_fetch_and_index()` then `ctx_search()`.
Direct bash only for git/mkdir/rm/mv/cd/ls/npm/pip; use `ctx_batch_execute()` for everything else.
"""
