// API client – all calls to /ui/api/*

import type { Config, Message, ModelOption, Session } from "../types";

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
    model: string;
    max_tokens?: number;
  },
  callbacks: StreamCallbacks
): AbortController {
  const ctrl = new AbortController();

  async function run() {
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
      callbacks.onError("Connection failed");
      return;
    }

    if (!res.ok) {
      const err = await res
        .json()
        .catch(() => ({ detail: `HTTP ${res.status}` }));
      callbacks.onError(
        (err as { detail?: string }).detail ?? `HTTP ${res.status}`
      );
      return;
    }

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

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
              callbacks.onDelta(evt.delta.text ?? "");
            } else if (evt.type === "error") {
              callbacks.onError(evt.error?.message ?? "Stream error");
              return;
            }
          } catch {
            // Ignore malformed JSON lines
          }
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        callbacks.onError("Stream interrupted");
      }
      return;
    }

    callbacks.onDone();
  }

  void run();
  return ctrl;
}
