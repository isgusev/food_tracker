// Переиспользуемые компоненты: модалка, поиск-выбор, КБЖУ, редактор ингредиентов.
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from "../vendor/vue.esm-browser.prod.js";
import { activeVariants, variantIndex } from "./store.js";
import { fmt, grams, matches, n } from "./util.js";

export const Modal = {
  props: { title: String, wide: Boolean },
  emits: ["close"],
  setup(_, { emit }) {
    const onKey = (e) => { if (e.key === "Escape") emit("close"); };
    onMounted(() => document.addEventListener("keydown", onKey));
    onBeforeUnmount(() => document.removeEventListener("keydown", onKey));
    return {};
  },
  template: `
    <div class="modal-backdrop" @mousedown.self="$emit('close')">
      <div class="modal" :class="{ wide }" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h2>{{ title }}</h2>
          <button class="ghost icon" @click="$emit('close')" aria-label="Закрыть">✕</button>
        </div>
        <div class="modal-body"><slot /></div>
        <div class="modal-foot" v-if="$slots.foot"><slot name="foot" /></div>
      </div>
    </div>`,
};

// Поиск с выпадающим списком. items: [{ id, label, sub?, group?, right? }]
export const Picker = {
  props: {
    items: { type: Array, required: true },
    modelValue: [Number, String, null],
    placeholder: { type: String, default: "Начните вводить…" },
    autofocus: Boolean,
  },
  emits: ["update:modelValue", "pick"],
  setup(props, { emit }) {
    const query = ref("");
    const open = ref(false);
    const hl = ref(0);
    const input = ref(null);
    const selected = computed(() => props.items.find((i) => i.id === props.modelValue));
    watch(selected, (s) => { if (s && !open.value) query.value = s.label; }, { immediate: true });

    const filtered = computed(() => {
      const q = open.value && selected.value && query.value === selected.value.label ? "" : query.value;
      return props.items.filter((i) => matches(`${i.label} ${i.sub || ""} ${i.group || ""}`, q)).slice(0, 80);
    });
    const rows = computed(() => {
      const out = [];
      let g = null;
      filtered.value.forEach((item, idx) => {
        if (item.group && item.group !== g) { g = item.group; out.push({ header: g, key: "g" + g }); }
        out.push({ item, idx, key: item.id });
      });
      return out;
    });
    function pick(item) {
      emit("update:modelValue", item.id);
      emit("pick", item);
      query.value = item.label;
      open.value = false;
    }
    function onKey(e) {
      if (!open.value && ["ArrowDown", "Enter"].includes(e.key)) { open.value = true; return; }
      if (e.key === "ArrowDown") { hl.value = Math.min(hl.value + 1, filtered.value.length - 1); e.preventDefault(); }
      else if (e.key === "ArrowUp") { hl.value = Math.max(hl.value - 1, 0); e.preventDefault(); }
      else if (e.key === "Enter") { const it = filtered.value[hl.value]; if (it) pick(it); e.preventDefault(); }
      else if (e.key === "Escape") { open.value = false; e.stopPropagation(); }
    }
    function onBlur() {
      setTimeout(() => {
        open.value = false;
        if (selected.value) query.value = selected.value.label;
      }, 150);
    }
    watch(query, () => { hl.value = 0; });
    onMounted(() => { if (props.autofocus) nextTick(() => input.value?.focus()); });
    return { query, open, hl, rows, pick, onKey, onBlur, input };
  },
  template: `
    <div class="picker">
      <input ref="input" v-model="query" :placeholder="placeholder" @focus="open = true; $event.target.select()"
             @input="open = true" @keydown="onKey" @blur="onBlur" autocomplete="off">
      <div class="picker-list" v-if="open && rows.length">
        <template v-for="r in rows" :key="r.key">
          <div v-if="r.header" class="picker-group">{{ r.header }}</div>
          <div v-else class="picker-item" :class="{ hl: r.idx === hl }" @mousedown.prevent="pick(r.item)">
            <span class="grow"><span>{{ r.item.label }}</span>
              <span v-if="r.item.sub" class="muted small"> · {{ r.item.sub }}</span></span>
            <span v-if="r.item.right" class="muted small nowrap num">{{ r.item.right }}</span>
          </div>
        </template>
      </div>
      <div class="picker-list" v-else-if="open && query"><div class="picker-item muted">Ничего не найдено</div></div>
    </div>`,
};

export const Macros = {
  props: { m: Object, digits: { type: Number, default: 0 }, kcalOnly: Boolean },
  setup() { return { fmt }; },
  template: `
    <span class="macros">
      <span class="macro"><i class="dot k"></i>{{ fmt(m.calories) }} ккал</span>
      <template v-if="!kcalOnly">
        <span class="macro"><i class="dot p"></i>Б {{ fmt(m.proteins, digits) }}</span>
        <span class="macro"><i class="dot f"></i>Ж {{ fmt(m.fats, digits) }}</span>
        <span class="macro"><i class="dot c"></i>У {{ fmt(m.carbs, digits) }}</span>
      </template>
    </span>`,
};

export const MacroMeters = {
  props: { value: Object, target: Object },
  setup(props) {
    const rows = computed(() => [
      { k: "calories", cls: "k", label: "Калории", unit: "ккал" },
      { k: "proteins", cls: "p", label: "Белки", unit: "г" },
      { k: "fats", cls: "f", label: "Жиры", unit: "г" },
      { k: "carbs", cls: "c", label: "Углеводы", unit: "г" },
    ].map((r) => {
      const v = n(props.value[r.k]);
      const t = n(props.target[r.k]);
      const pct = t > 0 ? (v / t) * 100 : 0;
      return { ...r, v, t, pct: Math.min(pct, 100), over: pct > 110 };
    }));
    return { rows, fmt };
  },
  template: `
    <div class="target-grid">
      <div v-for="r in rows" :key="r.k" class="stack tight">
        <div class="row between small"><span class="muted">{{ r.label }}</span>
          <span class="num"><b>{{ fmt(r.v) }}</b><span class="muted"> / {{ fmt(r.t) }} {{ r.unit }}</span></span></div>
        <div class="meter" :class="r.cls"><i :class="{ over: r.over }" :style="{ width: r.pct + '%' }"></i></div>
      </div>
    </div>`,
};

// Выбор активной версии продукта
export const VariantPicker = {
  components: { Picker },
  props: { modelValue: [Number, null], autofocus: Boolean, placeholder: String },
  emits: ["update:modelValue", "pick"],
  setup() {
    const items = computed(() => activeVariants.value.map((v) => ({
      id: v.id, label: v.name, sub: v.sub, group: v.category || "Без категории",
      right: `${fmt(v.calories)} ккал`,
    })));
    return { items };
  },
  template: `<Picker :items="items" :modelValue="modelValue" :autofocus="autofocus"
               :placeholder="placeholder || 'Продукт…'"
               @update:modelValue="$emit('update:modelValue', $event)" @pick="$emit('pick', $event)" />`,
};

// Редактор состава: [{ variant_id, weight_g }] + итоговый вес/КБЖУ
export const IngredientsEditor = {
  components: { VariantPicker, Macros },
  props: { modelValue: { type: Array, required: true }, cookedWeight: [Number, String] },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const rows = computed(() => props.modelValue);
    function update(i, patch) {
      const next = props.modelValue.map((r, j) => (j === i ? { ...r, ...patch } : r));
      emit("update:modelValue", next);
    }
    function add() { emit("update:modelValue", [...props.modelValue, { variant_id: null, weight_g: 100 }]); }
    function remove(i) { emit("update:modelValue", props.modelValue.filter((_, j) => j !== i)); }
    const totals = computed(() => {
      const t = { raw: 0, calories: 0, proteins: 0, fats: 0, carbs: 0 };
      for (const r of props.modelValue) {
        const v = variantIndex.value[r.variant_id];
        const w = n(r.weight_g);
        t.raw += w;
        if (!v) continue;
        t.calories += (v.calories * w) / 100;
        t.proteins += (v.proteins * w) / 100;
        t.fats += (v.fats * w) / 100;
        t.carbs += (v.carbs * w) / 100;
      }
      return t;
    });
    const per100 = computed(() => {
      const cw = n(props.cookedWeight);
      if (!cw) return null;
      const k = 100 / cw;
      const t = totals.value;
      return { calories: t.calories * k, proteins: t.proteins * k, fats: t.fats * k, carbs: t.carbs * k };
    });
    const oldVersion = (id) => id && variantIndex.value[id] && !variantIndex.value[id].active;
    return { rows, update, add, remove, totals, per100, grams, variantIndex, oldVersion };
  },
  template: `
    <div class="stack tight">
      <div v-for="(r, i) in rows" :key="i" class="row" style="flex-wrap: nowrap">
        <div class="grow">
          <VariantPicker :modelValue="r.variant_id" @update:modelValue="update(i, { variant_id: $event })"
            :placeholder="oldVersion(r.variant_id) ? variantIndex[r.variant_id].label + ' (стар. версия)' : 'Продукт…'" />
        </div>
        <input type="number" min="0.1" step="any" style="width: 90px" :value="r.weight_g"
               @input="update(i, { weight_g: $event.target.value })" aria-label="Вес, г">
        <span class="muted small">г</span>
        <button class="ghost icon" @click="remove(i)" title="Убрать">✕</button>
      </div>
      <div class="row between">
        <button class="sm" @click="add">+ Ингредиент</button>
        <span class="small muted">Сырой вес: <b class="num">{{ grams(totals.raw) }}</b></span>
      </div>
      <div class="small" v-if="per100"><span class="muted">На 100 г готового: </span><Macros :m="per100" :digits="1" /></div>
    </div>`,
};

// Сканер штрихкода: камера + BarcodeDetector (Chrome/Android, Chrome на Mac),
// иначе — ручной ввод цифр. Камера доступна только на https или localhost.
export const BarcodeScanner = {
  components: { Modal },
  emits: ["close", "code"],
  setup(_, { emit }) {
    const video = ref(null);
    const manual = ref("");
    const status = ref("");
    const supported = "BarcodeDetector" in window && !!navigator.mediaDevices?.getUserMedia;
    let stream = null;
    let timer = null;
    async function start() {
      if (!supported) { status.value = "Этот браузер не умеет сканировать — введите цифры под штрихкодом."; return; }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        video.value.srcObject = stream;
        await video.value.play();
        const detector = new window.BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
        status.value = "Наведите камеру на штрихкод";
        timer = setInterval(async () => {
          try {
            const found = await detector.detect(video.value);
            if (found.length) { stop(); emit("code", found[0].rawValue); }
          } catch { /* кадр не готов */ }
        }, 300);
      } catch {
        status.value = "Нет доступа к камере (нужен https или localhost) — введите цифры вручную.";
      }
    }
    function stop() {
      clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    onMounted(start);
    onBeforeUnmount(stop);
    const submit = () => { const c = manual.value.replace(/\D/g, ""); if (c.length >= 8) { stop(); emit("code", c); } };
    return { video, manual, status, supported, submit };
  },
  template: `
    <Modal title="Штрихкод" @close="$emit('close')">
      <video v-if="supported" ref="video" playsinline muted style="width: 100%; border-radius: 10px; background: #000; max-height: 50vh"></video>
      <div class="small muted">{{ status }}</div>
      <div class="row" style="flex-wrap: nowrap">
        <input v-model="manual" inputmode="numeric" placeholder="4600000000000" @keydown.enter="submit">
        <button class="primary" @click="submit">Найти</button>
      </div>
    </Modal>`,
};
