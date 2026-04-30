import { useCallback, useEffect, useRef, useState } from "react";
import Login from "./components/Login";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import Header from "./components/Header";
import * as api from "./lib/api";
import type { Message, ModelOption, Session, ImageAttachment } from "./types";

export default function App() {
  // ── Auth ─────────────────────────────────────────────────────────────────
  const [token, setToken] = useState<string | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  // ── Data ─────────────────────────────────────────────────────────────────
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<ModelOption | null>(null);

  // ── UI state ─────────────────────────────────────────────────────────────
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // ── Verify stored token on mount ──────────────────────────────────────────
  useEffect(() => {
    const stored = api.getStoredToken();
    if (!stored) {
      setAuthChecked(true);
      return;
    }
    api
      .verifyToken(stored)
      .then((valid) => {
        if (valid) setToken(stored);
        else api.clearToken();
        setAuthChecked(true);
      })
      .catch(() => {
        api.clearToken();
        setAuthChecked(true);
      });
  }, []);

  // ── Load sessions + config after login ───────────────────────────────────
  const loadSessions = useCallback(async () => {
    if (!token) return;
    try {
      const list = await api.listSessions(token);
      setSessions(list);
    } catch {
      // silence
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    void loadSessions();
    api
      .fetchConfig(token)
      .then((m) => {
        setModels(m);
        setSelectedModel(m.find((x) => x.is_default) ?? m[0] ?? null);
      })
      .catch(() => {});
  }, [token, loadSessions]);

  // ── Load messages when active session changes ─────────────────────────────
  useEffect(() => {
    if (!token || !activeSessionId) {
      setMessages([]);
      return;
    }
    setLoadingMessages(true);
    api
      .fetchMessages(token, activeSessionId)
      .then((msgs) => {
        setMessages(msgs);
      })
      .catch(() => {
        setMessages([]);
      })
      .finally(() => setLoadingMessages(false));
  }, [token, activeSessionId]);

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleLogin = useCallback((tok: string) => {
    api.storeToken(tok);
    setToken(tok);
  }, []);

  const handleLogout = useCallback(async () => {
    if (token) await api.logout(token);
    setToken(null);
    setSessions([]);
    setMessages([]);
    setActiveSessionId(null);
  }, [token]);

  const handleNewChat = useCallback(async () => {
    if (!token) return;
    const session = await api.createSession(token, {
      title: "New Chat",
      model: selectedModel?.claude_model ?? "claude-opus-4-20250514",
    });
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(session.id);
    setMessages([]);
    setSidebarOpen(false);
    setError(null);
  }, [token, selectedModel]);

  const handleSelectSession = useCallback(
    (id: string) => {
      if (isStreaming) return;
      setActiveSessionId(id);
      setSidebarOpen(false);
      setError(null);
    },
    [isStreaming]
  );

  const handleDeleteSession = useCallback(
    async (id: string) => {
      if (!token) return;
      await api.deleteSession(token, id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
        setMessages([]);
      }
    },
    [token, activeSessionId]
  );

  const handleRenameSession = useCallback(
    async (id: string, title: string) => {
      if (!token) return;
      const updated = await api.renameSession(token, id, title);
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, ...updated } : s))
      );
    },
    [token]
  );

  const handleSendMessage = useCallback(
    async (content: string, images: ImageAttachment[] = []) => {
      if (
        !token ||
        !activeSessionId ||
        isStreaming ||
        (!content.trim() && images.length === 0)
      )
        return;
      setError(null);

      // Optimistic: add user message immediately
      const tempId = `temp-${Date.now()}`;
      // Build a preview-friendly content string
      const tempContent =
        images.length > 0
          ? JSON.stringify([
              ...images.map((img) => ({
                type: "image",
                source: {
                  type: "base64",
                  media_type: img.media_type,
                  data: img.data,
                },
              })),
              ...(content.trim()
                ? [{ type: "text", text: content.trim() }]
                : []),
            ])
          : content.trim();
      const tempMsg: Message = {
        id: tempId,
        session_id: activeSessionId,
        role: "user",
        content: tempContent,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, tempMsg]);
      setIsStreaming(true);
      setStreamingText("");

      let accText = "";
      const ctrl = api.streamChat(
        token,
        {
          session_id: activeSessionId,
          content: content.trim(),
          images: images.map((img) => ({
            media_type: img.media_type,
            data: img.data,
          })),
          model: selectedModel?.claude_model ?? "claude-opus-4-20250514",
          max_tokens: 8192,
        },
        {
          onDelta: (text) => {
            accText += text;
            setStreamingText(accText);
          },
          onDone: async () => {
            setIsStreaming(false);
            setStreamingText("");
            // Reload canonical messages from DB
            const msgs = await api.fetchMessages(token, activeSessionId);
            setMessages(msgs);
            // Refresh session list (title + updated_at may have changed)
            void loadSessions();
          },
          onError: (msg) => {
            setIsStreaming(false);
            setStreamingText("");
            setError(msg);
            // Remove optimistic user message on error
            setMessages((prev) => prev.filter((m) => m.id !== tempId));
          },
        }
      );
      abortRef.current = ctrl;
    },
    [token, activeSessionId, isStreaming, selectedModel, loadSessions]
  );

  const handleStopStreaming = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setStreamingText("");
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────

  if (!authChecked) {
    return (
      <div className="flex h-full items-center justify-center bg-[#0d0f14]">
        <div className="w-5 h-5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!token) {
    return <Login onLogin={handleLogin} />;
  }

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;

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
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          onDeleteSession={handleDeleteSession}
          onRenameSession={handleRenameSession}
          onClose={() => setSidebarOpen(false)}
        />
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        <Header
          session={activeSession}
          models={models}
          selectedModel={selectedModel}
          onSelectModel={setSelectedModel}
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
          onLogout={handleLogout}
          onNewChat={handleNewChat}
        />

        <main className="flex flex-1 flex-col overflow-hidden">
          <ChatView
            messages={messages}
            streamingText={isStreaming ? streamingText : null}
            isLoading={loadingMessages}
            isStreaming={isStreaming}
            error={error}
            hasSession={activeSessionId !== null}
            onSend={handleSendMessage}
            onStop={handleStopStreaming}
            onNewChat={handleNewChat}
          />
        </main>
      </div>
    </div>
  );
}
