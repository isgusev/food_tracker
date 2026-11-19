// Покупки: подписи количества, оценка суммы и офлайн-очередь отметок «куплено» (тот же ключ, что у старого).
import { reactive } from "vue";
import { ApiError, api, ok, type Schemas } from "./api/client";
import { toast } from "./session";
import { fmtQty, local, num } from "./util";

export type ShopList = Schemas["ShoppingListOut"];
export type Line = Schemas["ShoppingLineResponse"];
type Qty = { package_amount?: string | null; package_count?: number | null; needed?: string | null; unit: string };

/** «2 × 930 мл», «1 шт»; без упаковки — сколько нужно. */
export function pkgText(l: Qty): string {
  if (l.package_amount && l.package_count) {
    const one = fmtQty(l.package_amount, l.unit);
    return l.package_count === 1 && l.unit === "pcs" && num(l.package_amount) === 1 ? fmtQty(1, "pcs") : `${l.package_count} × ${one}`;
  }
  return l.needed ? fmtQty(l.needed, l.unit) : "";
}
/** Сколько всего берём (в единице товара). */
export const lineQty = (l: Qty) => (l.package_amount && l.package_count ? num(l.package_amount) * l.package_count : num(l.needed));

// ---- офлайн-очередь: в магазине без сети отметка ставится сразу, на сервер уходит, когда связь вернётся
type Queued = { id: number; kind: "check" | "uncheck" };
const QKEY = "ft.shopQueue";
export const queue = reactive<{ items: Queued[] }>({ items: local.get<Queued[]>(QKEY, []) });
const saveQueue = () => local.set(QKEY, queue.items);

const post = (id: number, kind: Queued["kind"]) =>
  kind === "check"
    ? ok(api.POST("/api/v1/shopping-lists/lines/{line_id}/check", { params: { path: { line_id: id } }, body: {} }))
    : ok(api.POST("/api/v1/shopping-lists/lines/{line_id}/uncheck", { params: { path: { line_id: id } } }));

/** Отметить строку; нет сети — в очередь (одна запись на строку, последняя побеждает), ответ null. */
export async function toggleLine(l: Line, kind: Queued["kind"]): Promise<ShopList | null> {
  try { return await post(l.id, kind); }
  catch (e) {
    if (!(e instanceof ApiError) || e.status !== 0) throw e;
    queue.items = queue.items.filter((q) => q.id !== l.id).concat({ id: l.id, kind });
    saveQueue();
    l.is_checked = kind === "check";
    toast("Нет сети — отметка отправится, когда связь вернётся");
    return null;
  }
}

/** Отправить накопленное; не сетевые ошибки (строку удалили, уже отмечено) молча выбрасываются. */
export async function flushQueue(): Promise<void> {
  if (!queue.items.length) return;
  const rest: Queued[] = [];
  for (const q of queue.items) {
    try { await post(q.id, q.kind); }
    catch (e) { if (e instanceof ApiError && e.status === 0) rest.push(q); }
  }
  queue.items = rest;
  saveQueue();
  if (!rest.length) toast("Отметки, сделанные без сети, отправлены");
}
