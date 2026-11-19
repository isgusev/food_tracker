// Пачки «Честного знака»: помощники для окон запасов.
import type { Schemas } from "../../api/client";
import { catalog } from "../../catalog";
import type { Pack } from "./PacksEditor.vue";

/** Пачки → тело запроса (пачка без даты — null, «без срока»). */
export const packsBody = (packs: Pack[]) => packs.map((p) => ({ code: p.code || null, expires_on: p.expires_on || null }));

/** Размер пачки по умолчанию: первая упаковка товара, иначе подсказка. */
export function defaultPackAmount(product: Schemas["ProductResponse"] | null, fallback: number | string = ""): number | string {
  const pk = product?.packages || [];
  return pk.length ? Number(pk[0].amount) : fallback;
}

export const productById = (id: number | null) => catalog.products.find((p) => p.id === id) ?? null;

/** Причины движений запасов — как в истории товара. */
export const REASON: Record<string, string> = {
  purchase: "покупка", manual: "добавлено", inventory: "инвентаризация", cook: "готовка", eat: "съедено", write_off: "списано",
};
