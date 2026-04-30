import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy, User, X } from "lucide-react";
import { useCallback, useState } from "react";
import type { Message } from "../types";

interface Props {
  message: Message;
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
function parseContent(raw: string): { text: string; images: string[] } {
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
      const images = blocks
        .filter((b) => b.type === "image" && b.source?.type === "base64")
        .map((b) => `data:${b.source!.media_type};base64,${b.source!.data}`);
      return { text, images };
    } catch {
      // fall through to plain text
    }
  }
  return { text: raw, images: [] };
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

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const { text, images } = parseContent(message.content);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-2 animate-fade-in">
        {lightboxSrc && (
          <ImageLightbox
            src={lightboxSrc}
            onClose={() => setLightboxSrc(null)}
          />
        )}
        <div className="flex items-end gap-2 max-w-[80%]">
          <div className="rounded-2xl rounded-br-sm bg-blue-600 px-4 py-2.5 text-sm text-white shadow-md shadow-blue-900/20">
            {images.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {images.map((src, i) => (
                  <img
                    key={i}
                    src={src}
                    alt={`image ${i + 1}`}
                    className="max-h-48 max-w-[240px] rounded-lg object-cover cursor-pointer hover:opacity-90 transition-opacity"
                    onClick={() => setLightboxSrc(src)}
                  />
                ))}
              </div>
            )}
            {text && <p className="whitespace-pre-wrap break-words">{text}</p>}
          </div>
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600/20 border border-blue-500/20">
            <User className="h-3.5 w-3.5 text-blue-400" />
          </div>
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
        <div className="message-prose min-w-0 flex-1 rounded-2xl rounded-tl-sm bg-[#1a1d25] px-4 py-3 text-sm text-surface-100 shadow">
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
                      <SyntaxHighlighter
                        style={vscDarkPlus}
                        language={match[1]}
                        PreTag="div"
                        customStyle={{
                          margin: 0,
                          background: "transparent",
                          padding: "12px 14px",
                          fontSize: "0.8125rem",
                        }}
                        {...props}
                      >
                        {code}
                      </SyntaxHighlighter>
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
