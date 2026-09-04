/** Build-time-only Tailwind configuration. The deployed UI uses no CDN. */
module.exports = {
  content: [
    "./web_app/static/index.html",
    "./web_app/static/app.js"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"]
      },
      colors: {
        frost: {
          50: "#f0f7fa", 100: "#e1f0f7", 200: "#bae6fd",
          300: "#7dd3fc", 400: "#38bdf8", 500: "#0ea5e9",
          600: "#0284c7", 700: "#0369a1", 800: "#075985",
          900: "#0c4a6e"
        },
        cadnavy: {800: "#1e293b", 900: "#0f172a", 950: "#090d16"}
      }
    }
  },
  plugins: [require("@tailwindcss/forms")]
};
