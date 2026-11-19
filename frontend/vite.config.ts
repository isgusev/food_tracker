import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vite";
import vue from "@vitejs/plugin-vue";

// Service worker: sw.js из корня frontend/ + список файлов сборки (без карт кода, редких шрифтов и сканера — он
// большой и без сети не нужен) → dist/sw.js. Версия — хеш списка: изменилась сборка — браузер ставит новый sw.
function serviceWorker(): Plugin {
  return {
    name: "ft-service-worker",
    apply: "build",
    generateBundle(_opts, bundle) {
      // вьетнамский и расширенную латиницу заголовочного шрифта браузер грузит, только если встретит такие буквы;
      // у основного (Golos) расширенная латиница нужна — в ней знак ₽
      const files = Object.keys(bundle).filter((f) => !f.endsWith(".map") && f !== "sw.js" && !/(vietnamese|unbounded-latin-ext)/.test(f));
      const extra = ["index.html", "manifest.webmanifest", "icon.svg", "icons/icon-192.png", "icons/apple-touch-icon.png"];
      const list = [...new Set([...extra, ...files])].sort();
      const version = createHash("sha256").update(list.join("\n")).digest("hex").slice(0, 12);
      const source = readFileSync(new URL("./sw.js", import.meta.url), "utf8")
        .replace('"__VERSION__"', JSON.stringify(version))
        .replace("__PRECACHE__", JSON.stringify(list));
      this.emitFile({ type: "asset", fileName: "sw.js", source });
    },
  };
}

// Новый интерфейс раздаётся API на /next/ (старый — на /app/, пока переезжаем).
// Разработка: `npm run dev` — запросы /api проксируются на uvicorn (по умолчанию :8000, VITE_API — другой адрес).
export default defineConfig({
  base: "/next/",
  plugins: [vue(), serviceWorker()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API || "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: true },
});
