<script setup lang="ts">
// Выбор из списка с поиском: все слова — подстроки (подпись, группа, ключи) или нечётко (≥ 0,6) по подписи.
// Клавиатура: ↓/Enter открыть, ↑↓ подсветка, Enter выбрать, Esc закрыть. Крестик — очистить.
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { fuzzyScore, matches } from "../util";

export interface PickerItem {
  id: number | string;
  label: string;
  sub?: string;
  group?: string;
  right?: string;
  right2?: string;
  keys?: string;
}

const props = withDefaults(defineProps<{ items: PickerItem[]; modelValue: number | string | null; placeholder?: string; autofocus?: boolean }>(),
  { placeholder: "Начните вводить…" });
const emit = defineEmits<{ "update:modelValue": [id: number | string]; pick: [item: PickerItem] }>();

const query = ref("");
const open = ref(false);
const hl = ref(0);
const input = ref<HTMLInputElement | null>(null);
const selected = computed(() => props.items.find((i) => i.id === props.modelValue));
watch(selected, (s) => { if (s && !open.value) query.value = s.label; }, { immediate: true });

const filtered = computed(() => {
  const q = open.value && selected.value && query.value === selected.value.label ? "" : query.value;
  return props.items.filter((i) => matches(`${i.label} ${i.sub || ""} ${i.group || ""} ${i.keys || ""}`, q)
    || (q && fuzzyScore(q, `${i.label} ${i.sub || ""}`) >= 0.6)).slice(0, 80);
});
const rows = computed(() => {
  const out: ({ header: string; key: string } | { item: PickerItem; idx: number; key: string })[] = [];
  let g: string | undefined;
  filtered.value.forEach((item, idx) => {
    if (item.group && item.group !== g) { g = item.group; out.push({ header: g, key: "g" + g }); }
    out.push({ item, idx, key: String(item.id) });
  });
  return out;
});
function pick(item: PickerItem) {
  emit("update:modelValue", item.id);
  emit("pick", item);
  query.value = item.label;
  open.value = false;
}
function onKey(e: KeyboardEvent) {
  if (!open.value && ["ArrowDown", "Enter"].includes(e.key)) { open.value = true; return; }
  if (e.key === "ArrowDown") { hl.value = Math.min(hl.value + 1, filtered.value.length - 1); e.preventDefault(); }
  else if (e.key === "ArrowUp") { hl.value = Math.max(hl.value - 1, 0); e.preventDefault(); }
  else if (e.key === "Enter") { const it = filtered.value[hl.value]; if (it) pick(it); e.preventDefault(); }
  else if (e.key === "Escape") { open.value = false; e.stopPropagation(); }
}
function onBlur() {
  setTimeout(() => { open.value = false; if (selected.value) query.value = selected.value.label; }, 150);
}
function clear() { query.value = ""; open.value = true; input.value?.focus(); }
watch(query, () => { hl.value = 0; });
onMounted(() => { if (props.autofocus) nextTick(() => input.value?.focus()); });
</script>

<template>
  <div class="picker">
    <div class="clearable">
      <input ref="input" v-model="query" :placeholder="placeholder" autocomplete="off" role="combobox" :aria-expanded="open"
             @focus="open = true; ($event.target as HTMLInputElement).select()" @input="open = true" @keydown="onKey" @blur="onBlur">
      <button v-if="query" type="button" class="clear" aria-label="Очистить" @mousedown.prevent="clear">✕</button>
    </div>
    <div v-if="open && rows.length" class="list" role="listbox">
      <template v-for="r in rows" :key="r.key">
        <div v-if="'header' in r" class="group">{{ r.header }}</div>
        <div v-else class="opt" :class="{ hl: r.idx === hl }" role="option" :aria-selected="r.idx === hl" @mousedown.prevent="pick(r.item)">
          <span class="lbl"><span>{{ r.item.label }}</span><span v-if="r.item.sub" class="sub">{{ r.item.sub }}</span></span>
          <span v-if="r.item.right" class="right"><span>{{ r.item.right }}</span><span v-if="r.item.right2" class="tiny">{{ r.item.right2 }}</span></span>
        </div>
      </template>
    </div>
    <div v-else-if="open && query" class="list"><div class="opt muted">Ничего не найдено</div></div>
  </div>
</template>

<style scoped>
.picker { position: relative; }
.clearable { position: relative; }
.clearable input { padding-right: 44px; }
.clear { position: absolute; right: 2px; top: 50%; transform: translateY(-50%); min-height: 40px; min-width: 40px; padding: 0;
  border: 0; color: var(--muted); font-weight: 400; }
.list { position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 60; max-height: 300px; overflow-y: auto;
  background: var(--enamel); border: 1.5px solid var(--rim); border-radius: var(--r-in); }
.group { padding: 8px 12px 2px; font-size: 12px; color: var(--muted); font-weight: 600; }
.opt { display: flex; justify-content: space-between; gap: 10px; padding: 9px 12px; cursor: pointer; }
.opt.hl, .opt:hover { background: var(--rim-soft); }
.lbl { min-width: 0; display: flex; flex-direction: column; }
.sub { font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.right { display: flex; flex-direction: column; align-items: flex-end; flex: none; color: var(--muted); font-size: 13px; white-space: nowrap; }
</style>
