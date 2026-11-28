import { build, createServer, preview } from "vite";
import react from "@vitejs/plugin-react";

const mode = process.argv[2] || "dev";

const config = {
  configFile: false,
  plugins: [react()],
  build: {
    minify: false,
    target: "esnext",
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
};

if (mode === "build") {
  await build(config);
} else if (mode === "preview") {
  const server = await preview(config);
  server.printUrls();
} else {
  const server = await createServer(config);
  await server.listen();
  server.printUrls();
}

