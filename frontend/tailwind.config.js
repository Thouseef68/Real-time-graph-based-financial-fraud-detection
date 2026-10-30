/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        "card-foreground": "hsl(var(--card-foreground))",
        primary: {
          DEFAULT: "#4F46E5", // Indigo accent
          foreground: "#FFFFFF",
          50: "#EEF2FF",
          100: "#E0E7FF",
          500: "#6366F1",
          600: "#4F46E5",
          700: "#4338CA",
        },
        risk: {
          low: "#10B981", // Emerald
          medium: "#F59E0B", // Amber
          high: "#F97316", // Orange
          critical: "#EF4444", // Red
        },
        slate: {
          850: "#151e2e",
          900: "#0F172A",
          950: "#090D16",
        },
      },
      borderRadius: {
        xl: "0.75rem",
        "2xl": "1rem",
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
      },
    },
  },
  plugins: [],
};
