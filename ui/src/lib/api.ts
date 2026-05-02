// API client – all calls to /ui/api/*

import type { Config, MemoryEntry, Message, ModelOption, Session } from "../types";

const BASE = "/ui/api";

// ── Auth helpers ──────────────────────────────────────────────────────────────

const TOKEN_KEY = "fcc_ui_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(token: string): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

// ── Generic fetch helpers ─────────────────────────────────────────────────────

async function post<T>(
  path: string,
  body: unknown,
  token?: string
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(
      res.status,
      (err as { detail?: string }).detail ?? res.statusText
    );
  }
  return res.json() as Promise<T>;
}

async function get<T>(path: string, token: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders(token) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(
      res.status,
      (err as { detail?: string }).detail ?? res.statusText
    );
  }
  return res.json() as Promise<T>;
}

async function patch<T>(
  path: string,
  body: unknown,
  token: string
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(
      res.status,
      (err as { detail?: string }).detail ?? res.statusText
    );
  }
  return res.json() as Promise<T>;
}

async function del(path: string, token: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(
      res.status,
      (err as { detail?: string }).detail ?? res.statusText
    );
  }
}

// ── Error type ────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(password: string): Promise<string> {
  const data = await post<{ token: string }>("/auth/login", { password });
  return data.token;
}

export async function logout(token: string): Promise<void> {
  await post("/auth/logout", {}, token).catch(() => {});
  clearToken();
}

/** Verify a stored token by hitting a lightweight protected endpoint. */
export async function verifyToken(token: string): Promise<boolean> {
  try {
    await get<Config>("/config", token);
    return true;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return false;
    throw e;
  }
}

// ── Config ────────────────────────────────────────────────────────────────────

export async function fetchConfig(token: string): Promise<ModelOption[]> {
  const data = await get<Config>("/config", token);
  return data.models;
}

// ── Sessions ──────────────────────────────────────────────────────────────────

export async function listSessions(token: string): Promise<Session[]> {
  return get<Session[]>("/sessions", token);
}

export async function createSession(
  token: string,
  opts: { title?: string; model?: string } = {}
): Promise<Session> {
  return post<Session>("/sessions", opts, token);
}

export async function renameSession(
  token: string,
  id: string,
  title: string
): Promise<Session> {
  return patch<Session>(`/sessions/${id}`, { title }, token);
}

export async function deleteSession(token: string, id: string): Promise<void> {
  return del(`/sessions/${id}`, token);
}

// ── Messages ──────────────────────────────────────────────────────────────────

export async function fetchMessages(
  token: string,
  sessionId: string
): Promise<Message[]> {
  return get<Message[]>(`/sessions/${sessionId}/messages`, token);
}

// ── Summary ──────────────────────────────────────────────────────────────────

export async function fetchSummary(
  token: string,
  sessionId: string
): Promise<string | null> {
  try {
    const data = await get<{ summary: string | null }>(
      `/sessions/${sessionId}/summary`,
      token
    );
    return data.summary;
  } catch {
    return null;
  }
}

// ── Global Memory ────────────────────────────────────────────────────────────

export async function fetchMemory(
  token: string
): Promise<MemoryEntry[]> {
  return get<MemoryEntry[]>("/memory", token);
}

export async function deleteMemory(
  token: string,
  key: string
): Promise<void> {
  return del(`/memory/${encodeURIComponent(key)}`, token);
}

// ── Streaming chat ────────────────────────────────────────────────────────────

export interface StreamCallbacks {
  onDelta: (text: string) => void;
  onDone: () => void;
  onError: (msg: string) => void;
}

/**
 * Stream a chat message.  Streams the raw SSE response from the backend and
 * calls `onDelta` for each text_delta, `onDone` on completion, `onError` on
 * failure.  Returns an `AbortController` so the caller can cancel.
 */
export function streamChat(
  token: string,
  payload: {
    session_id: string;
    content: string;
    images?: Array<{ media_type: string; data: string }>;
    model: string;
    max_tokens?: number;
  },
  callbacks: StreamCallbacks
): AbortController {
  const ctrl = new AbortController();

  async function run() {
    const MAX_RETRIES = 2;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      if (attempt > 0) {
        // Exponential backoff: 1s, 2s
        await new Promise((r) => setTimeout(r, 1000 * attempt));
        if (ctrl.signal.aborted) return;
      }

      let res: Response;
      try {
        res = await fetch(`${BASE}/chat`, {
          method: "POST",
          headers: authHeaders(token),
          body: JSON.stringify(payload),
          signal: ctrl.signal,
        });
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        if (attempt < MAX_RETRIES) continue;
        callbacks.onError("Connection failed");
        return;
      }

      if (!res.ok) {
        const err = await res
          .json()
          .catch(() => ({ detail: `HTTP ${res.status}` }));
        // Retry on 5xx, surface 4xx immediately
        if (res.status >= 500 && attempt < MAX_RETRIES) continue;
        callbacks.onError(
          (err as { detail?: string }).detail ?? `HTTP ${res.status}`
        );
        return;
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let receivedContent = false;
      let streamError: string | null = null;

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const data = line.slice(5).trim();
            if (!data || data === "[DONE]") continue;
            try {
              const evt = JSON.parse(data) as {
                type?: string;
                delta?: { type?: string; text?: string };
                error?: { message?: string };
              };
              if (
                evt.type === "content_block_delta" &&
                evt.delta?.type === "text_delta"
              ) {
                receivedContent = true;
                callbacks.onDelta(evt.delta.text ?? "");
              } else if (evt.type === "error") {
                streamError = evt.error?.message ?? "Stream error";
              }
            } catch {
              // Ignore malformed JSON lines
            }
          }

          if (streamError) break;
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        // Network drop mid-stream
        if (!receivedContent && attempt < MAX_RETRIES) continue;
        // If we already had content, gracefully end rather than showing error
        if (receivedContent) {
          callbacks.onDone();
          return;
        }
        callbacks.onError("Stream interrupted – please try again");
        return;
      }

      if (streamError) {
        if (!receivedContent && attempt < MAX_RETRIES) continue;
        if (receivedContent) {
          callbacks.onDone();
          return;
        }
        callbacks.onError(streamError);
        return;
      }

      callbacks.onDone();
      return;
    }
  }

  void run();
  return ctrl;
}
