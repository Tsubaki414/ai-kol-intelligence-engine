/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Dune Analytics / Cookie3 dark palette
        bg: {
          base: "#0F1117",
          panel: "#151821",
          card: "#1A1E2A",
          hover: "#232838",
        },
        border: {
          DEFAULT: "#2A3040",
          subtle: "#1F2431",
        },
        accent: {
          blue: "#3B82F6",
          emerald: "#10B981",
          amber: "#F59E0B",
          rose: "#F43F5E",
          purple: "#A855F7",
        },
        text: {
          primary: "#E6EBF5",
          secondary: "#94A3B8",
          muted: "#64748B",
          dim: "#475569",
        },
        tier: {
          t1: "#10B981",
          t2: "#3B82F6",
          t3: "#64748B",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'SFMono-Regular', 'Consolas', 'monospace'],
        sans: ['"DM Sans"', '-apple-system', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glow: "0 0 20px rgba(59, 130, 246, 0.3)",
        "glow-emerald": "0 0 20px rgba(16, 185, 129, 0.3)",
      },
    },
  },
  plugins: [],
};
