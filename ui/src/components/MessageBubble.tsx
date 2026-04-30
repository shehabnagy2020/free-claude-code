import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy, RotateCcw, User, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Message, ModelOption } from "../types";

interface Props {
  message: Message;
  models?: ModelOption[];
  onResend?: (
    content: string,
    imageBlocks: Array<{ media_type: string; data: string }>,
    model: string
  ) => void;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 rounded px-1.5 py-1 text-xs text-surface-400 hover:text-white hover:bg-white/10 transition"
      title="Copy code"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-400" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** Parse message content – may be plain text or a JSON array of Anthropic content blocks. */
function parseContent(raw: string): {
  text: string;
  images: string[];
  rawImageBlocks: Array<{ media_type: string; data: string }>;
} {
  if (raw.startsWith("[")) {
    try {
      const blocks = JSON.parse(raw) as Array<{
        type: string;
        text?: string;
        source?: { type: string; media_type: string; data: string };
      }>;
      const text = blocks
        .filter((b) => b.type === "text")
        .map((b) => b.text ?? "")
        .join("\n");
      const imageBlocks = blocks.filter(
        (b) => b.type === "image" && b.source?.type === "base64"
      );
      const images = imageBlocks.map(
        (b) => `data:${b.source!.media_type};base64,${b.source!.data}`
      );
      const rawImageBlocks = imageBlocks.map((b) => ({
        media_type: b.source!.media_type,
        data: b.source!.data,
      }));
      return { text, images, rawImageBlocks };
    } catch {
      // fall through to plain text
    }
  }
  return { text: raw, images: [], rawImageBlocks: [] };
}

function ImageLightbox({ src, onClose }: { src: string; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <button
        className="absolute top-4 right-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20 transition"
        onClick={onClose}
        aria-label="Close"
      >
        <X className="h-5 w-5" />
      </button>
      <img
        src={src}
        alt="Full size"
        className="max-h-[90vh] max-w-[90vw] rounded-xl object-contain shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}

export default function MessageBubble({ message, models, onResend }: Props) {
  const isUser = message.role === "user";
  const { text, images, rawImageBlocks } = parseContent(message.content);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [loadedSet, setLoadedSet] = useState<Set<number>>(() => new Set());
  const [resendOpen, setResendOpen] = useState(false);
  const resendRef = useRef<HTMLDivElement>(null);

  const markLoaded = useCallback((i: number) => {
    setLoadedSet((prev) => {
      const s = new Set(prev);
      s.add(i);
      return s;
    });
  }, []);

  // Close resend dropdown on outside click
  useEffect(() => {
    if (!resendOpen) return;
    function handler(e: MouseEvent) {
      if (resendRef.current && !resendRef.current.contains(e.target as Node)) {
        setResendOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [resendOpen]);

  if (isUser) {
    return (
      <div className="group flex justify-end px-4 py-2 animate-fade-in min-w-0">
        {lightboxSrc && (
          <ImageLightbox
            src={lightboxSrc}
            onClose={() => setLightboxSrc(null)}
          />
        )}
        <div className="flex flex-col items-end gap-1 min-w-0 max-w-[80%]">
          <div className="flex items-end gap-2 min-w-0">
            <div className="rounded-2xl rounded-br-sm bg-blue-600 px-4 py-2.5 text-sm text-white shadow-md shadow-blue-900/20 break-words overflow-hidden">
              {images.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {images.map((src, i) => (
                    <div
                      key={i}
                      className="relative rounded-lg overflow-hidden"
                      style={{
                        width: loadedSet.has(i) ? undefined : 80,
                        height: loadedSet.has(i) ? undefined : 80,
                      }}
                    >
                      {!loadedSet.has(i) && (
                        <div className="absolute inset-0 flex items-center justify-center bg-blue-500/30 rounded-lg">
                          <div className="w-5 h-5 rounded-full border-2 border-white/60 border-t-transparent animate-spin" />
                        </div>
                      )}
                      <img
                        src={src}
                        alt={`image ${i + 1}`}
                        className={`max-h-48 max-w-[240px] rounded-lg object-cover cursor-pointer hover:opacity-90 transition-opacity ${
                          loadedSet.has(i) ? "opacity-100" : "opacity-0"
                        }`}
                        onLoad={() => markLoaded(i)}
                        onClick={() => setLightboxSrc(src)}
                      />
                    </div>
                  ))}
                </div>
              )}
              {text && (
                <p className="whitespace-pre-wrap break-words">{text}</p>
              )}
            </div>
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600/20 border border-blue-500/20">
              <User className="h-3.5 w-3.5 text-blue-400" />
            </div>
          </div>

          {/* Resend with model picker */}
          {onResend && models && models.length > 0 && (
            <div
              ref={resendRef}
              className="relative mr-9 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <button
                onClick={() => setResendOpen((v) => !v)}
                className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-surface-500 hover:text-surface-200 hover:bg-white/8 transition"
              >
                <RotateCcw className="h-3 w-3" />
                Resend
              </button>
              {resendOpen && (
                <div className="absolute bottom-full mb-1 right-0 z-20 min-w-[160px] rounded-xl border border-white/10 bg-[#1a1d25] p-1 shadow-xl">
                  <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-surface-500">
                    Choose model
                  </p>
                  {models.map((m) => (
                    <button
                      key={m.claude_model}
                      onClick={() => {
                        setResendOpen(false);
                        onResend(text, rawImageBlocks, m.claude_model);
                      }}
                      className="w-full rounded-lg px-3 py-2 text-left text-xs text-surface-200 hover:bg-white/10 transition"
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start px-4 py-2 animate-fade-in">
      <div className="flex items-start gap-2.5 max-w-[88%]">
        {/* Avatar */}
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/15 border border-amber-500/20 mt-0.5">
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5 text-amber-400"
            fill="currentColor"
          >
            <path
              d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
              stroke="currentColor"
              fill="none"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        {/* Content */}
        <div className="message-prose min-w-0 flex-1 rounded-2xl rounded-tl-sm bg-[#1a1d25] px-4 py-3 text-sm text-surface-100 shadow break-words overflow-hidden">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkBreaks]}
            components={{
              code({
                inline,
                className,
                children,
                ...props
              }: {
                inline?: boolean;
                className?: string;
                children?: React.ReactNode;
              }) {
                const match = /language-(\w+)/.exec(className ?? "");
                const code = String(children ?? "").replace(/\n$/, "");
                if (!inline && match) {
                  return (
                    <div className="not-prose my-3 overflow-hidden rounded-xl border border-white/8 bg-[#0d0f14]">
                      <div className="flex items-center justify-between border-b border-white/8 px-3 py-1.5">
                        <span className="text-xs text-surface-500 font-mono">
                          {match[1]}
                        </span>
                        <CopyButton text={code} />
                      </div>
                      <div className="overflow-x-hidden">
                        <SyntaxHighlighter
                          style={vscDarkPlus}
                          language={match[1]}
                          PreTag="div"
                          customStyle={{
                            margin: 0,
                            background: "transparent",
                            padding: "12px 14px",
                            fontSize: "0.8125rem",
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-all",
                          }}
                          {...props}
                        >
                          {code}
                        </SyntaxHighlighter>
                      </div>
                    </div>
                  );
                }
                return (
                  <code
                    className="rounded bg-white/10 px-1 py-0.5 font-mono text-[0.8125rem] text-amber-300"
                    {...props}
                  >
                    {children}
                  </code>
                );
              },
            }}
          >
            {text}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
