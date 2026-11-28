import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    minify: false,
    target: 'esnext',
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        headers: { "X-API-Key": "a8a23b926e076df558878fb651ac2b832757296c77d64ede" },
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
