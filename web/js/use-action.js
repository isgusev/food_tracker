// Действие с сервером из компонента: «занято», ошибка, тост — одинаково везде.
//
//   const { busy, error, run } = useAction({ inline: true, done: (res) => emit("saved", res) });
//   const save = () => run(() => api.post(...), "Сохранено");
//
// run(fn, msg) — выполняет fn, затем done(res) и тост msg; возвращает результат fn или undefined при ошибке.
// inline — ошибка пишется в error (показать в окне), иначе — тостом.
import { ref } from "../vendor/vue.esm-browser.prod.js";
import { toast, toastError } from "./store.js";

export function useAction({ inline = false, done = null } = {}) {
  const busy = ref(false);
  const error = ref("");
  async function run(fn, msg) {
    error.value = "";
    busy.value = true;
    try {
      const res = await fn();
      if (done) await done(res);
      if (msg) toast(msg);
      return res;
    } catch (e) {
      if (inline) error.value = e.message;
      else toastError(e);
      return undefined;
    } finally {
      busy.value = false;
    }
  }
  return { busy, error, run };
}
