import { type KeyboardEvent, useCallback, useRef, useState } from "react";
import { MessageSquare, PencilLine, Plus, Trash2, X } from "lucide-react";
import type { Session } from "../types";

interface Props {
  sessions: Session[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
  onClose: () => void;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 6) return new Date(iso).toLocaleDateString();
  if (d >= 1) return `${d}d ago`;
  if (h >= 1) return `${h}h ago`;
  if (m >= 1) return `${m}m ago`;
  return "Just now";
}

interface SessionRowProps {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onRename: (title: string) => void;
}

function SessionRow({
  session,
  isActive,
  onSelect,
  onDelete,
  onRename,
}: SessionRowProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(session.title);
  const [hovering, setHovering] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      setEditValue(session.title);
      setEditing(true);
      setTimeout(() => inputRef.current?.select(), 50);
    },
    [session.title]
  );

  const commitEdit = useCallback(() => {
    const val = editValue.trim();
    if (val && val !== session.title) onRename(val);
    setEditing(false);
  }, [editValue, session.title, onRename]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") commitEdit();
      else if (e.key === "Escape") setEditing(false);
    },
    [commitEdit]
  );

  const handleDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onDelete();
    },
    [onDelete]
  );

  return (
    <li
      className={[
        "group relative flex cursor-pointer items-start gap-2.5 rounded-xl px-3 py-2.5 transition-colors",
        isActive
          ? "bg-white/10 text-white"
          : "text-surface-300 hover:bg-white/6 hover:text-white",
      ].join(" ")}
      onClick={onSelect}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => {
        setHovering(false);
      }}
    >
      <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-surface-500" />

      <div className="min-w-0 flex-1">
        {editing ? (
          <input
            ref={inputRef}
            className="w-full rounded bg-white/10 px-1.5 py-0.5 text-sm text-white outline-none ring-2 ring-blue-500/50"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={handleKeyDown}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <p className="truncate text-sm font-medium">{session.title}</p>
        )}
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-surface-500">
          <span>{relativeTime(session.updated_at)}</span>
          {(session.message_count ?? 0) > 0 && (
            <>
              <span>·</span>
              <span>
                {session.message_count} msg
                {(session.message_count ?? 0) !== 1 ? "s" : ""}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Action buttons */}
      {hovering && !editing && (
        <div
          className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-0.5"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className="rounded p-1 text-surface-400 hover:text-white hover:bg-white/10 transition"
            onClick={startEdit}
            title="Rename"
          >
            <PencilLine className="h-3.5 w-3.5" />
          </button>
          <button
            className="rounded p-1 transition text-surface-400 hover:text-red-400 hover:bg-white/10"
            onClick={handleDelete}
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </li>
  );
}

export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onRenameSession,
  onClose,
}: Props) {
  return (
    <div className="flex h-full flex-col bg-[#111318] border-r border-white/8">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3.5 border-b border-white/8">
        <span className="text-sm font-semibold text-white">Chats</span>
        <button
          className="rounded-lg p-1.5 text-surface-400 hover:text-white hover:bg-white/8 transition md:hidden"
          onClick={onClose}
          title="Close sidebar"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* New chat button */}
      <div className="px-3 py-2.5">
        <button
          onClick={onNewChat}
          className="flex w-full items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-surface-300 hover:text-white hover:bg-white/10 transition"
        >
          <Plus className="h-4 w-4" />
          New Chat
        </button>
      </div>

      {/* Session list */}
      <ul className="custom-scrollbar flex-1 overflow-y-auto px-2 pb-3 space-y-0.5">
        {sessions.length === 0 ? (
          <li className="px-3 py-8 text-center text-sm text-surface-500">
            No chats yet.
            <br />
            Start one above!
          </li>
        ) : (
          sessions.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              isActive={s.id === activeSessionId}
              onSelect={() => onSelectSession(s.id)}
              onDelete={() => onDeleteSession(s.id)}
              onRename={(title) => onRenameSession(s.id, title)}
            />
          ))
        )}
      </ul>
    </div>
  );
}
