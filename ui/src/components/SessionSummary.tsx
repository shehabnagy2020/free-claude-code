import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";

interface Props {
  summary: string;
}

function parseRememberItems(text: string): {
  content: string;
  rememberItems: string[];
} {
  const lines = text.split("\n");
  const rememberItems = lines
    .filter((l) => l.trim().startsWith("REMEMBER:"))
    .map((l) => l.replace("REMEMBER:", "").trim());
  const content = lines
    .filter((l) => !l.trim().startsWith("REMEMBER:"))
    .join("\n")
    .trim();
  return { content, rememberItems };
}

export default function SessionSummary({ summary }: Props) {
  const [expanded, setExpanded] = useState(false);
  const { content, rememberItems } = parseRememberItems(summary);

  if (!summary.trim()) return null;

  return (
    <div className="mx-4 mt-3 mb-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-surface-500 hover:text-surface-300 transition group"
      >
        <FileText className="h-3.5 w-3.5" />
        <span className="font-medium">Session Summary</span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
      </button>

      {expanded && (
        <div className="mt-1.5 rounded-xl bg-[#1a1d25]/60 border border-white/5 px-3 py-2 text-xs text-surface-400 leading-relaxed animate-fade-in">
          {content && <p>{content}</p>}
          {rememberItems.length > 0 && (
            <div className="mt-2 pt-2 border-t border-white/5">
              <p className="text-amber-400/70 font-medium mb-1">
                Pinned memories:
              </p>
              {rememberItems.map((item, i) => (
                <p key={i} className="text-amber-300/60">
                  {item}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {!expanded && rememberItems.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {rememberItems.slice(0, 3).map((item, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400/70"
            >
              {item.length > 40 ? item.slice(0, 40) + "…" : item}
            </span>
          ))}
          {rememberItems.length > 3 && (
            <span className="text-[10px] text-surface-500">
              +{rememberItems.length - 3} more
            </span>
          )}
        </div>
      )}
    </div>
  );
}