import { LogOut, Menu, Plus } from "lucide-react";
import ModelSelector from "./ModelSelector";
import type { ModelOption, Session } from "../types";

interface Props {
  session: Session | null;
  models: ModelOption[];
  selectedModel: ModelOption | null;
  onSelectModel: (model: ModelOption) => void;
  onToggleSidebar: () => void;
  onLogout: () => void;
  onNewChat: () => void;
}

export default function Header({
  session,
  models,
  selectedModel,
  onSelectModel,
  onToggleSidebar,
  onLogout,
  onNewChat,
}: Props) {
  return (
    <header className="flex h-13 shrink-0 items-center gap-2 border-b border-white/8 bg-[#0d0f14]/80 px-3 backdrop-blur-sm">
      {/* Sidebar toggle (mobile only) */}
      <button
        onClick={onToggleSidebar}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-surface-400 hover:text-white hover:bg-white/8 transition md:hidden"
        title="Toggle sidebar"
      >
        <Menu className="h-4.5 w-4.5" />
      </button>

      {/* Session title */}
      <div className="flex-1 min-w-0">
        {session ? (
          <p className="truncate text-sm font-medium text-white">
            {session.title}
          </p>
        ) : (
          <p className="text-sm text-surface-500">No chat selected</p>
        )}
      </div>

      {/* Model selector */}
      <ModelSelector
        models={models}
        selected={selectedModel}
        onSelect={onSelectModel}
      />

      {/* New chat (desktop shortcut) */}
      <button
        onClick={onNewChat}
        className="hidden md:flex h-8 w-8 items-center justify-center rounded-lg text-surface-400 hover:text-white hover:bg-white/8 transition"
        title="New chat"
      >
        <Plus className="h-4.5 w-4.5" />
      </button>

      {/* Logout */}
      <button
        onClick={onLogout}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-surface-400 hover:text-red-400 hover:bg-red-500/10 transition"
        title="Sign out"
      >
        <LogOut className="h-4 w-4" />
      </button>
    </header>
  );
}
