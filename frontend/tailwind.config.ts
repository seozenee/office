import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { pixel: ["Galmuri11", "Galmuri9", "monospace"], body: ["Galmuri11", "system-ui", "sans-serif"] },
      colors: {
        ink: "#1b1d2a",
        panel: "#2a2d3e",
        panel2: "#343850",
        line: "#4b5070",
        cream: "#f4ecd8",
        accent: "#ffcc4d",
        mint: "#6ee7b7",
        rose: "#fb7185",
        sky: "#7dd3fc",
      },
      boxShadow: {
        pixel: "0 0 0 2px #0e0f16, 4px 4px 0 0 #0e0f16",
        pixelsm: "0 0 0 2px #0e0f16, 2px 2px 0 0 #0e0f16",
        inset: "inset 0 0 0 2px #0e0f16",
      },
    },
  },
  plugins: [],
};
export default config;
