import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { ModelOption } from "../types";

interface Props {
  models: ModelOption[];
  selected: ModelOption | null;
  onSelect: (model: ModelOption) => void;
}

export default function ModelSelector({ models, selected, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (!selected || models.length === 0) return null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-surface-300 hover:text-white hover:bg-white/10 transition"
      >
        <span className="max-w-[140px] truncate">{selected.label}</span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-64 overflow-hidden rounded-xl border border-white/10 bg-[#1a1d25] shadow-2xl shadow-black/50 animate-fade-in">
          <div className="max-h-72 overflow-y-auto custom-scrollbar py-1">
            {models.map((m) => (
              <button
                key={m.claude_model}
                onClick={() => {
                  onSelect(m);
                  setOpen(false);
                }}
                className={[
                  "flex w-full flex-col gap-0.5 px-3 py-2.5 text-left transition hover:bg-white/8",
                  m.claude_model === selected.claude_model ? "bg-white/8" : "",
                ].join(" ")}
              >
                <span className="text-sm font-medium text-white">
                  {m.label}
                </span>
                {m.provider_display && (
                  <span className="text-xs text-surface-500">
                    {m.provider_display}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
