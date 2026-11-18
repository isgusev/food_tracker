#!/bin/bash
# Проверка фронтенда без браузера и без Node: JavaScriptCore (есть в macOS) загружает все ES-модули web/js
# (ловит синтаксические ошибки и несуществующие импорты) и компилирует шаблоны всех Vue-компонентов,
# до которых дотягивается из экспортов (ловит ошибки выражений и директив в template: `…`).
# Не ловит: незакрытые теги (продакшен-сборка Vue их прощает) и ошибки, которые видны только при работе экрана
# (несуществующая переменная в setup) — это всё ещё проверка в браузере.
#   scripts/check_web.sh        → «checked components: N, template errors: 0», код возврата 1 при ошибках
set -euo pipefail
JSC=/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# app.js не грузим: он сразу монтирует приложение в DOM (а экраны и компоненты, которые он подключает, — проверяем)
FILES=$(cd "$ROOT/web" && ls js/*.js js/views/*.js | grep -v '^js/app.js$' | sed 's/.*/"&"/' | paste -sd, -)
cat > "$TMP/check.mjs" <<EOF
// шим: компилятор Vue декодирует сущности через document.createElement
const decode = (s) => s.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&");
globalThis.document = { createElement: () => ({
  set innerHTML(v) {
    this.textContent = decode(v);
    const m = /^<div foo="([\s\S]*)">$/.exec(v);
    this.children = [{ getAttribute: () => (m ? decode(m[1]) : "") }];
  },
}) };
globalThis.window = globalThis;
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
globalThis.navigator = { onLine: true };
globalThis.location = { hash: "", origin: "", pathname: "/" };
globalThis.addEventListener = () => {};
const W = "$ROOT/web/";
const { compile } = await import(W + "vendor/vue.esm-browser.prod.js");
let bad = 0;
const seen = new Set();
function check(name, c) {
  if (!c || typeof c !== "object" || seen.has(c)) return;
  seen.add(c);
  if (typeof c.template === "string") {
    try {
      compile(c.template, { onError: (e) => { bad++; print(name + ": " + e.message); }, onWarn: () => {} });
    } catch (e) { bad++; print(name + " throw: " + e); }
  }
  for (const [k, sub] of Object.entries(c.components || {})) check(name + ">" + k, sub);
}
for (const f of [$FILES]) {
  let mod;
  try { mod = await import(W + f); } catch (e) { bad++; print(f + " load: " + e); continue; }
  for (const [k, v] of Object.entries(mod)) check(f + ":" + k, v);
}
print("checked components: " + seen.size + ", template errors: " + bad);
if (bad) throw new Error("web check failed");
EOF
"$JSC" -m "$TMP/check.mjs"
# офлайн: каждый модуль web/js должен быть в списке SHELL service worker'а
MISSING=$(cd "$ROOT/web" && find js -name '*.js' | sort | while read -r f; do grep -q "\"$f\"" sw.js || echo "$f"; done)
if [ -n "$MISSING" ]; then echo "нет в SHELL web/sw.js (поднимите и CACHE):"; echo "$MISSING"; exit 1; fi
echo "sw.js SHELL: все модули на месте"
