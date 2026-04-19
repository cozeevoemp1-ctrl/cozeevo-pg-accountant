import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F6F5F0",
        surface: "#FFFFFF",
        ink: {
          DEFAULT: "#0F0E0D",
          muted: "#6F655D",
        },
        brand: {
          pink: "#EF1F9C",
          blue: "#00AEED",
        },
        status: {
          paid: "#2A7A2A",
          due: "#EF1F9C",
          warn: "#C25000",
        },
        tile: {
          green: "#E1F3DF",
          pink: "#FCE2EE",
          blue: "#DFF0FB",
          orange: "#FFE8D0",
        },
      },
      fontFamily: {
        sans: ["var(--font-dm-sans)", "system-ui", "sans-serif"],
      },
      borderRadius: {
        card: "18px",
        tile: "14px",
        pill: "12px",
      },
    },
  },
  plugins: [],
} satisfies Config;
