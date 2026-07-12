/** Tailwind config for the NSCLC Atlas webview. Compiled to a static
 *  media/atlas/atlas.css at build time — no PostCSS runs inside the webview.
 *  Content globs are resolved from the repo root (esbuild.mjs runs there). */
module.exports = {
  content: ["./webview-src/atlas/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        panel: "#0f172a",
        panelLight: "#1e293b",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
