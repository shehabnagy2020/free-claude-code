// Shared TypeScript types for the web UI

export interface Session {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

/** A single image attached to a user message. */
export interface ImageAttachment {
  /** MIME type: image/jpeg | image/png | image/gif | image/webp */
  media_type: string;
  /** Base64-encoded image data (no data: URI prefix). */
  data: string;
  /** Local object URL for preview only – not persisted. */
  preview_url: string;
}

/**
 * A chat message.
 * `content` is either:
 *   - plain string  → text-only message
 *   - JSON array string → Anthropic content blocks [{type,source,...}, ...]
 */
export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ModelOption {
  label: string;
  claude_model: string;
  provider_display?: string;
  is_default: boolean;
}

export interface Config {
  models: ModelOption[];
}

export interface AuthState {
  token: string | null;
  isAuthenticated: boolean;
}
