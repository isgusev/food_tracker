import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Новый интерфейс раздаётся API на /next/ (старый — на /app/, пока переезжаем).
// Разработка: `npm run dev` — запросы /api проксируются на uvicorn (по умолчанию :8000, VITE_API — другой адрес).
export default defineConfig({
  base: "/next/",
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API || "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: true },
});
