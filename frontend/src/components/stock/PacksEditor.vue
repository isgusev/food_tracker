<script setup lang="ts">
// «Честный знак»: пачки с кодами маркировки. У каждой пачки свой срок (из кода, если производитель его записал,
// иначе — вручную); при сохранении пачки с одним сроком становятся одной партией, с разными — разными.
// v-model:packs — Pack[]; v-model:packAmount — сколько в пачке (единица товара); product — когда товар определился по коду.
import { computed, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { toast } from "../../session";
import { dayMonthShort, fmtQty, num, UNIT_LABEL } from "../../util";
import BarcodeScanner from "../finder/BarcodeScanner.vue";

export interface Pack { code: string | null; gtin?: string | null; serial: string | null; expires_on: string; fromCode: boolean }

const props = defineProps<{ product: Schemas["ProductResponse"] | null; packs: Pack[]; packAmount: number | string; max?: number }>();
const emit = defineEmits<{ "update:packs": [packs: Pack[]]; "update:packAmount": [v: number | string]; product: [id: number] }>();

const scanning = ref(false);
const unit = computed(() => props.product?.base_unit || "g");
const packages = computed(() => props.product?.packages || []);

async function onCode(code: string) {
  try {
    const m = await ok(api.POST("/api/v1/stock/marks/parse", { body: { code } }));
    if (m.already_registered) { toast("Эта пачка уже в запасах — её код сканировали раньше", "error"); return; }
    if (props.packs.some((p) => p.serial === m.serial && p.gtin === m.gtin)) return;   // та же пачка ещё раз — тихо
    if (props.product) {
      if ((props.product.barcode && props.product.barcode !== m.barcode) || (m.product_id && m.product_id !== props.product.id)) {
        toast(`Это код другого товара${m.product_name ? ` («${m.product_name}»)` : ""}`, "error");
        return;
      }
    } else if (m.product_id) {
      emit("product", m.product_id);
    } else {
      toast(`Товара со штрихкодом ${m.barcode} нет в справочнике — сначала добавьте его в «Продукты»`, "error", 6000);
      return;
    }
    emit("update:packs", [...props.packs, { code, gtin: m.gtin, serial: m.serial, expires_on: m.expires_on || "", fromCode: !!m.expires_on }]);
    if (!m.expires_on) toast("В коде нет срока годности — введите дату у этой пачки");
  } catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); }
}
function addManual() {
  const last = props.packs[props.packs.length - 1];
  emit("update:packs", [...props.packs, { code: null, serial: null, expires_on: last?.expires_on || "", fromCode: false }]);
}
const setDate = (i: number, v: string) => emit("update:packs", props.packs.map((p, j) => (j === i ? { ...p, expires_on: v } : p)));
const remove = (i: number) => emit("update:packs", props.packs.filter((_, j) => j !== i));

// «2 × до 20 окт · 1 без срока»
const summary = computed(() => {
  const g = new Map<string, number>();
  for (const p of props.packs) g.set(p.expires_on || "", (g.get(p.expires_on || "") || 0) + 1);
  return [...g.entries()].sort().map(([d, c]) => `${c} × ${d ? "до " + dayMonthShort(d) : "без срока"}`).join(" · ");
});
const total = computed(() => num(props.packAmount) * props.packs.length);
const overMax = computed(() => props.max != null && total.value > num(props.max) + 0.05);
</script>

<template>
  <div class="packs">
    <div class="row">
      <button class="fill" @click="scanning = true">📷 Сканировать пачки</button>
      <button @click="addManual">+ Пачка без кода</button>
    </div>
    <div class="row small">
      <span class="muted">В одной пачке</span>
      <select v-if="packages.length" class="auto" :value="num(packAmount)" aria-label="Упаковка"
              @change="emit('update:packAmount', Number(($event.target as HTMLSelectElement).value))">
        <option v-for="pk in packages" :key="pk.id" :value="num(pk.amount)">{{ fmtQty(pk.amount, unit) }}</option>
      </select>
      <input type="number" min="0.1" step="any" class="n3" :value="packAmount" aria-label="Сколько в одной пачке"
             @input="emit('update:packAmount', ($event.target as HTMLInputElement).value)">
      <span class="muted">{{ UNIT_LABEL[unit] }}</span>
    </div>
    <div v-if="packs.length" class="list">
      <div class="head small"><b>{{ packs.length }} пач. · {{ fmtQty(total, unit) }}</b><span class="muted">{{ summary }}</span></div>
      <div v-for="(p, i) in packs" :key="i" class="pack small">
        <span class="grow">Пачка {{ i + 1 }}<span class="muted"> · {{ p.code ? "код …" + (p.serial || "").slice(-4) : "без кода" }}</span></span>
        <span v-if="p.fromCode" class="badge" title="Срок прочитан из кода">до {{ dayMonthShort(p.expires_on) }}</span>
        <input v-else type="date" class="date" :value="p.expires_on" aria-label="Годен до"
               @input="setDate(i, ($event.target as HTMLInputElement).value)">
        <button class="text icon" title="Убрать пачку" aria-label="Убрать пачку" @click="remove(i)">✕</button>
      </div>
    </div>
    <p v-else class="tiny muted">Сканируйте квадратный код DataMatrix на каждой пачке: срок годности подставится сам, если производитель
      записал его в код; одну пачку дважды добавить нельзя.</p>
    <p v-if="overMax" class="note">Пачек больше, чем осталось в партии ({{ fmtQty(max, unit) }}).</p>
    <BarcodeScanner v-if="scanning" marks :count="packs.length" @close="scanning = false" @code="onCode" />
  </div>
</template>

<style scoped>
.packs { display: flex; flex-direction: column; gap: 10px; }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.auto { width: auto; }
.n3 { width: 92px; }
.list { border: 1.5px solid var(--line); border-radius: var(--r-in); overflow: hidden; }
.head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; padding: 8px 12px; background: var(--enamel-2); }
.pack { display: flex; align-items: center; gap: 8px; padding: 4px 4px 4px 12px; border-top: 1px solid var(--line); }
.grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.date { width: 160px; }
.badge { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: var(--rim-soft); color: var(--rim); white-space: nowrap; }
.icon { min-width: 44px; padding: 0; color: var(--muted); }
.note { margin: 0; padding: 10px 12px; border-radius: var(--r-in); background: var(--beak-soft); font-size: 14px; }
p { margin: 0; }
</style>
