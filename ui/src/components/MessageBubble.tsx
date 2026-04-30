import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy, User } from "lucide-react";
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

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-2 animate-fade-in">
        <div className="flex items-end gap-2 max-w-[80%]">
          <div className="rounded-2xl rounded-br-sm bg-blue-600 px-4 py-2.5 text-sm text-white shadow-md shadow-blue-900/20">
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
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
            {message.content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
