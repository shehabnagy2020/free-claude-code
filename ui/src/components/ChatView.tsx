import {
  useEffect,
  useRef,
  type FormEvent,
  useState,
  useCallback,
} from "react";
import { ArrowUp, MessageSquarePlus, Square } from "lucide-react";
import MessageBubble from "./MessageBubble";
import type { Message } from "../types";

interface Props {
  messages: Message[];
  streamingText: string | null;
  isLoading: boolean;
  isStreaming: boolean;
  error: string | null;
  hasSession: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
  onNewChat: () => void;
}

function TypingIndicator() {
  return (
    <div className="flex justify-start px-4 py-2">
      <div className="flex items-start gap-2.5">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/15 border border-amber-500/20 mt-0.5">
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5 text-amber-400"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
            />
          </svg>
        </div>
        <div className="rounded-2xl rounded-tl-sm bg-[#1a1d25] px-4 py-3 text-sm text-surface-300 shadow">
          <span className="flex gap-1">
            <span className="typing-dot" style={{ animationDelay: "0ms" }}>
              ●
            </span>
            <span className="typing-dot" style={{ animationDelay: "180ms" }}>
              ●
            </span>
            <span className="typing-dot" style={{ animationDelay: "360ms" }}>
              ●
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}

function StreamingBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-start px-4 py-2">
      <div className="flex items-start gap-2.5 max-w-[88%]">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/15 border border-amber-500/20 mt-0.5">
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5 text-amber-400"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
            />
          </svg>
        </div>
        <div className="min-w-0 flex-1 rounded-2xl rounded-tl-sm bg-[#1a1d25] px-4 py-3 text-sm text-surface-100 shadow">
          <p className="whitespace-pre-wrap break-words">{text}</p>
          <span className="inline-block w-0.5 h-3.5 bg-blue-400 animate-pulse ml-0.5 translate-y-0.5" />
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onNewChat }: { onNewChat: () => void }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="flex flex-col items-center gap-4 text-center max-w-sm animate-fade-in">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-600/15 border border-blue-500/20">
          <MessageSquarePlus className="h-7 w-7 text-blue-400" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-white">
            Start a conversation
          </h2>
          <p className="mt-1 text-sm text-surface-400">
            Select a chat or create a new one to begin.
          </p>
        </div>
        <button
          onClick={onNewChat}
          className="mt-1 rounded-xl bg-blue-600 px-5 py-2 text-sm font-semibold text-white shadow hover:bg-blue-500 transition active:scale-[0.97]"
        >
          New Chat
        </button>
      </div>
    </div>
  );
}

export default function ChatView({
  messages,
  streamingText,
  isLoading,
  isStreaming,
  error,
  hasSession,
  onSend,
  onStop,
  onNewChat,
}: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      e?.preventDefault();
      const txt = input.trim();
      if (!txt || isStreaming) return;
      setInput("");
      onSend(txt);
    },
    [input, isStreaming, onSend]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  if (!hasSession) {
    return <EmptyState onNewChat={onNewChat} />;
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Message list */}
      <div className="custom-scrollbar flex-1 overflow-y-auto py-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          </div>
        ) : messages.length === 0 && !streamingText ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-surface-500 text-sm">
            <MessageSquarePlus className="h-8 w-8 opacity-30" />
            <p>Send a message to begin</p>
          </div>
        ) : (
          <>
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            {isStreaming && !streamingText && <TypingIndicator />}
            {isStreaming && streamingText && (
              <StreamingBubble text={streamingText} />
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-4 mb-2 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-2.5 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Input area */}
      <div className="px-4 pb-4 pt-2">
        <form
          onSubmit={handleSubmit}
          className="flex items-end gap-2 rounded-2xl border border-white/10 bg-[#1a1d25] p-2 focus-within:border-blue-500/30 transition-colors"
        >
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isStreaming ? "Generating…" : "Message Claude…"}
            disabled={isStreaming}
            className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-white placeholder-surface-500 outline-none disabled:opacity-50"
          />

          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-red-500/80 text-white hover:bg-red-500 transition"
              title="Stop generation"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white hover:bg-blue-500 transition disabled:opacity-40 disabled:cursor-not-allowed active:scale-95"
              title="Send"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </form>
        <p className="mt-1.5 text-center text-xs text-surface-600">
          Shift+Enter for newline · Enter to send
        </p>
      </div>
    </div>
  );
}
