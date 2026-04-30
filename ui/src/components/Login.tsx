import { type FormEvent, useState } from "react";
import { login } from "../lib/api";

interface Props {
  onLogin: (token: string) => void;
}

export default function Login({ onLogin }: Props) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!password.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const token = await login(password.trim());
      onLogin(token);
    } catch {
      setError("Invalid password. Please try again.");
      setPassword("");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-[#0d0f14] p-4">
      <div className="w-full max-w-sm animate-fade-in">
        {/* Logo mark */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 shadow-lg shadow-blue-900/40">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              className="h-7 w-7 text-white"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-4l-4 4v-4z"
              />
            </svg>
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold text-white">Claude Chat</h1>
            <p className="text-sm text-surface-400">
              Enter your password to continue
            </p>
          </div>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-white/8 bg-[#161921] p-6 shadow-xl shadow-black/40"
        >
          <div className="mb-4">
            <label
              htmlFor="password"
              className="mb-1.5 block text-sm font-medium text-surface-300"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className={[
                "w-full rounded-xl border bg-[#1e2229] px-4 py-2.5 text-white placeholder-surface-500 outline-none transition",
                "focus:ring-2 focus:ring-blue-500/60",
                error
                  ? "border-red-500/60"
                  : "border-white/10 focus:border-blue-500/40",
              ].join(" ")}
            />
            {error && <p className="mt-1.5 text-sm text-red-400">{error}</p>}
          </div>

          <button
            type="submit"
            disabled={loading || !password.trim()}
            className="mt-2 w-full rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-md shadow-blue-900/30 transition hover:bg-blue-500 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Signing in…
              </span>
            ) : (
              "Sign in"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
