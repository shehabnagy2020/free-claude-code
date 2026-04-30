// Shared TypeScript types for the web UI

export interface Session {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ModelOption {
  label: string;
  target: string;
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
