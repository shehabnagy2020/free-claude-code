import { useState } from "react";
import { Brain, ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import type { MemoryEntry } from "../types";

interface Props {
  memory: MemoryEntry[];
  onDelete: (key: string) => void;
}

export default function GlobalMemoryPanel({ memory, onDelete }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (memory.length === 0) return null;

  return (
    <div className="px-3 py-1.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-surface-500 hover:text-surface-300 transition w-full"
      >
        <Brain className="h-3.5 w-3.5 text-amber-400/60" />
        <span className="font-medium">
          Memory ({memory.length})
        </span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
      </button>

      {expanded && (
        <div className="mt-1.5 space-y-1 animate-fade-in">
          {memory.map((entry) => (
            <div
              key={entry.key}
              className="group flex items-start gap-1.5 rounded-lg bg-white/5 px-2 py-1.5 text-[11px] text-surface-400"
            >
              <span className="flex-1 leading-snug break-words">
                {entry.value}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(entry.key);
                }}
                className="shrink-0 rounded p-0.5 text-surface-500 opacity-0 group-hover:opacity-100 hover:text-red-400 transition"
                title="Delete memory"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}