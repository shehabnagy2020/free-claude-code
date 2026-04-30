/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      spacing: {
        // Non-default sizes used throughout the UI
        4.5: "1.125rem", // icon size between h-4 and h-5
        13: "3.25rem", // header height
      },
      opacity: {
        // Fine-grained opacity stops used for subtle borders/backgrounds
        6: "0.06",
        8: "0.08",
        15: "0.15",
      },
      colors: {
        // App-specific colour tokens
        surface: {
          DEFAULT: "#0d0f14",
          card: "#13151a",
          elevated: "#1a1d24",
          border: "#1f2328",
          hover: "#1e2128",
          // Numeric shades used as text/bg utilities (e.g. text-surface-400)
          100: "#e8eaf0",
          200: "#c0c4d0",
          300: "#9099b0",
          400: "#636b80",
          500: "#454c5e",
          600: "#2e3342",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.15s ease-out",
        "slide-in": "slideIn 0.2s ease-out",
        "pulse-dot": "pulseDot 1.2s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideIn: {
          from: { transform: "translateX(-100%)" },
          to: { transform: "translateX(0)" },
        },
        pulseDot: {
          "0%, 100%": { opacity: "0.3", transform: "scale(0.75)" },
          "50%": { opacity: "1", transform: "scale(1.2)" },
        },
      },
    },
  },
  plugins: [],
};
