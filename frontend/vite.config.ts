import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": "/src",
    },
  },
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      output: {
        /* Split the three large, rarely-changing dependency groups into
         * their own chunks. This does not reduce the total bytes — it
         * makes them cacheable independently of application code (an
         * app-only change no longer invalidates the React or Motion
         * chunk) and lets the browser fetch them in parallel. The
         * measured split is reported in the sprint notes; `motion` is
         * the single largest addition this sprint, which is worth
         * knowing explicitly rather than hiding inside one 500 kB
         * bundle. */
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          motion: ["motion"],
          query: ["@tanstack/react-query"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
  },
});
