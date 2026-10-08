// Справочник продуктов: КБЖУ с версиями по производителям.
import { ref, computed, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Macros, BarcodeScanner, KbjuInputs } from "../components.js";
import { state, ensureCatalog, loadProducts, categoryName, toast, toastError } from "../store.js";
import { fmt, matches, n, packagesLabel } from "../util.js";
import { OffSearchModal } from "../product-finder.js";

const NewProductModal = {
  components: { Modal, KbjuInputs, BarcodeScanner, OffSearchModal },
  emits: ["close", "saved"],
  setup(_, { emit }) {
    const f = ref({ name: "", category: "", brand: "", manufacturer: "", kbju: { calories: "", proteins: "", fats: "", carbs: "" } });
    const busy = ref(false);
    const error = ref("");
    // Штрихкод: свой справочник → подсказка из Open Food Facts
    const barcode = ref("");
    const scanning = ref(false);
    const hint = ref("");
    const pkg = ref(null);   // упаковка из Open Food Facts: { unit, amount }
    const searching = ref(false);  // поиск по названию в Open Food Facts
    function fill(s) {
      Object.assign(f.value, { name: s.name || f.value.name, brand: s.brand || f.value.brand, manufacturer: s.manufacturer || f.value.manufacturer });
      f.value.kbju = { calories: s.calories ?? "", proteins: s.proteins ?? "", fats: s.fats ?? "", carbs: s.carbs ?? "" };
      pkg.value = s.package_amount ? { unit: s.package_unit || "g", amount: n(s.package_amount) } : null;
    }
    function pickFound(s) {
      searching.value = false;
      fill(s);
      if (s.barcode) barcode.value = s.barcode;
      hint.value = "Заполнено из Open Food Facts — проверьте цифры с упаковки.";
    }
    async function lookup(code) {
      scanning.value = false;
      barcode.value = code;
      hint.value = "Ищем…";
      try {
        const r = await api.get(`/products/barcode/${code}`);
        if (r.source === "local") { hint.value = `Уже есть в справочнике: «${r.product.name}» (${r.product.brand?.name || "без бренда"})`; return; }
        if (r.source === "none") { hint.value = "В Open Food Facts не нашли — заполните вручную, код сохранится."; return; }
        fill(r.suggestion);
        hint.value = "Заполнено из Open Food Facts — проверьте цифры с упаковки.";
      } catch (e) { hint.value = e.message; }
    }
    async function save() {
      error.value = "";
      const v = f.value;
      if (!v.name.trim() || !v.category.trim()) { error.value = "Укажите название и категорию"; return; }
      busy.value = true;
      try {
        await api.post("/products/with-category", {
          category_name: v.category.trim(),
          name: v.name.trim(),
          brand_name: v.brand.trim() || "Без бренда",
          barcode: /^\d{8,14}$/.test(barcode.value) ? barcode.value : null,
          // упаковка с этикетки: сервер переведёт в единицу товара (бутылка → мл)
          package_amount: pkg.value?.amount || null,
          package_unit: pkg.value?.amount ? pkg.value.unit : null,
          base_variant: {
            manufacturer_name: v.manufacturer.trim() || v.brand.trim() || null,
            calories: n(v.kbju.calories), proteins: n(v.kbju.proteins), fats: n(v.kbju.fats), carbs: n(v.kbju.carbs),
          },
        });
        await loadProducts();
        toast(`«${v.name}» добавлен`);
        emit("saved");
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    return { f, busy, error, save, state, barcode, scanning, hint, lookup, pkg, searching, pickFound };
  },
  template: `
    <Modal title="Новый продукт" @close="$emit('close')">
      <label class="field"><span>Штрихкод (необязательно)</span>
        <div class="row" style="flex-wrap: nowrap">
          <input v-model="barcode" inputmode="numeric" placeholder="4600000000000" @keydown.enter="barcode && lookup(barcode)">
          <button class="sm" @click="scanning = true" title="Сканировать камерой">📷</button>
          <button class="sm" :disabled="!barcode" @click="lookup(barcode)">Найти</button>
        </div>
        <span v-if="hint" class="tiny">{{ hint }}</span>
        <span v-if="pkg" class="tiny muted">Упаковка с этикетки: {{ pkg.amount }} {{ pkg.unit === 'ml' ? 'мл' : pkg.unit === 'pcs' ? 'шт' : 'г' }} — добавится к продукту{{ pkg.unit === 'pcs' ? ' (если товар учитывается в штуках)' : '' }}.</span>
      </label>
      <BarcodeScanner v-if="scanning" @close="scanning = false" @code="lookup" />
      <div class="field"><span>Название</span>
        <div class="row" style="flex-wrap: nowrap">
          <input v-model="f.name" placeholder="Йогурт греческий 2%" @keydown.enter="f.name.trim().length >= 2 && (searching = true)">
          <button class="sm" @click="searching = true" title="Найти по названию в Open Food Facts">🔎 Найти</button>
        </div>
        <span class="tiny muted">Можно найти по названию и бренду в Open Food Facts — КБЖУ, упаковка и штрихкод заполнятся сами.</span>
      </div>
      <OffSearchModal v-if="searching" :initial="f.name" @close="searching = false" @pick="pickFound" />
      <div class="grid-2">
        <label class="field"><span>Категория</span>
          <input v-model="f.category" list="cat-list" placeholder="Молочные продукты">
          <datalist id="cat-list"><option v-for="c in state.productCategories" :key="c.id" :value="c.name" /></datalist>
        </label>
        <label class="field"><span>Бренд</span><input v-model="f.brand" placeholder="Без бренда"></label>
      </div>
      <label class="field"><span>Производитель (если отличается от бренда)</span><input v-model="f.manufacturer"></label>
      <KbjuInputs v-model="f.kbju" />
      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy" @click="save">Сохранить</button>
      </template>
    </Modal>`,
};

const ProductModal = {
  components: { Modal, KbjuInputs, Macros, BarcodeScanner },
  props: { product: Object },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const adding = ref(null); // { manufacturer_name, kbju }
    const busy = ref(false);
    const error = ref("");
    const p = computed(() => state.products.find((x) => x.id === props.product.id) || props.product);
    function startAdd(m) {
      const active = m?.variants.find((v) => v.is_active) || {};
      adding.value = {
        manufacturer_name: m ? m.name || "" : "",
        isNew: !m,
        kbju: { calories: n(active.calories), proteins: n(active.proteins), fats: n(active.fats), carbs: n(active.carbs) },
      };
    }
    async function run(fn, msg) {
      error.value = ""; busy.value = true;
      try { await fn(); await loadProducts(); toast(msg); adding.value = null; }
      catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    const saveVariant = () => run(() => api.post(`/products/${p.value.id}/variants`, {
      manufacturer_name: adding.value.manufacturer_name.trim() || null,
      calories: n(adding.value.kbju.calories), proteins: n(adding.value.kbju.proteins),
      fats: n(adding.value.kbju.fats), carbs: n(adding.value.kbju.carbs),
    }), "Новая версия КБЖУ сохранена");
    const rollback = (m) => {
      if (!confirm("Вернуть предыдущую версию КБЖУ этого производителя?")) return;
      run(() => api.post(`/products/${p.value.id}/manufacturers/${m.id}/rollback`), "Откат выполнен");
    };
    const sortedVariants = (m) => [...m.variants].sort((a, b) => b.version - a.version);

    // Единица товара и упаковки (для списка покупок и запасов)
    const unit = ref(p.value.base_unit || "g");
    const piece = ref(p.value.piece_weight_g != null ? Number(p.value.piece_weight_g) : "");
    const pkgAmount = ref("");
    const pkgName = ref("");
    const saveUnit = () => run(() => api.put(`/products/${p.value.id}/unit`, {
      base_unit: unit.value, piece_weight_g: unit.value === "pcs" ? n(piece.value) || null : null,
    }), "Единица сохранена — для всех брендов этого товара");
    const addPkg = () => n(pkgAmount.value) > 0 && run(() => api.post(`/products/${p.value.id}/packages`, { amount: n(pkgAmount.value), name: pkgName.value || null }), "Упаковка добавлена")
      .then(() => { pkgAmount.value = ""; pkgName.value = ""; });
    const delPkg = (pk) => run(() => api.del(`/products/packages/${pk.id}`), "Упаковка удалена");
    const unitLabel = { g: "г", ml: "мл", pcs: "шт" };
    // Штрихкод: чтобы в следующий раз найти продукт сканером
    const code = ref(p.value.barcode || "");
    const scanningCode = ref(false);
    const validCode = computed(() => /^\d{8,14}$/.test(code.value));
    const saveCode = () => validCode.value && run(() => api.put(`/products/${p.value.id}/barcode`, { barcode: code.value }), "Штрихкод сохранён");
    const onScanCode = (c) => { scanningCode.value = false; code.value = c; saveCode(); };
    return { code, validCode, scanningCode, saveCode, onScanCode, p, adding, busy, error, startAdd, saveVariant, rollback, sortedVariants, categoryName, fmt, unit, piece, pkgAmount, pkgName, saveUnit, addPkg, delPkg, unitLabel };
  },
  template: `
    <Modal :title="p.name" wide @close="$emit('close')">
      <div class="row small muted"><span class="badge">{{ categoryName[p.category_id] }}</span><span>Бренд: {{ p.brand?.name }}</span></div>
      <div class="row small">
        <span class="muted">Штрихкод</span>
        <input v-model="code" inputmode="numeric" placeholder="не задан" style="width: 160px" @keydown.enter="saveCode">
        <button class="sm" @click="scanningCode = true" title="Сканировать камерой">📷</button>
        <button v-if="code !== (p.barcode || '')" class="sm" :disabled="busy || !validCode" @click="saveCode">Сохранить</button>
      </div>
      <BarcodeScanner v-if="scanningCode" @close="scanningCode = false" @code="onScanCode" />
      <div class="card stack">
        <h3>Покупка и учёт запасов</h3>
        <div class="row">
          <div class="segmented">
            <button :class="{ on: unit === 'g' }" @click="unit = 'g'">граммы</button>
            <button :class="{ on: unit === 'ml' }" @click="unit = 'ml'">мл</button>
            <button :class="{ on: unit === 'pcs' }" @click="unit = 'pcs'">штуки</button>
          </div>
          <template v-if="unit === 'pcs'"><span class="small muted">1 шт =</span><input type="number" min="1" step="any" v-model="piece" style="width: 80px"><span class="small muted">г</span></template>
          <button class="sm" :disabled="busy" @click="saveUnit">Сохранить</button>
        </div>
        <div class="tiny muted">Единица общая для всех брендов этого товара. Рецепты и КБЖУ — всегда в граммах; штуки пересчитываются по весу одной.</div>
        <div class="row">
          <span class="small">Упаковки:</span>
          <span v-for="pk in p.packages" :key="pk.id" class="badge">{{ fmt(pk.amount, pk.amount % 1 ? 1 : 0) }} {{ unitLabel[p.base_unit || 'g'] }}<template v-if="pk.name"> · {{ pk.name }}</template>
            <button class="ghost" style="padding: 0 0 0 4px; border: none" @click="delPkg(pk)" title="Удалить">✕</button></span>
          <span v-if="!p.packages?.length" class="small muted">нет</span>
        </div>
        <div class="row">
          <input type="number" min="0.1" step="any" v-model="pkgAmount" placeholder="Сколько в упаковке" style="width: 160px">
          <input v-model="pkgName" placeholder="Название (пачка…)" style="width: 160px">
          <button class="sm" :disabled="busy || !pkgAmount" @click="addPkg">+ Упаковка</button>
        </div>
      </div>
      <div v-for="m in p.manufacturers" :key="m.id" class="card flush">
        <div class="row between" style="padding: 10px 14px; border-bottom: 1px solid var(--border)">
          <h3>{{ m.name || 'Без производителя' }}</h3>
          <div class="row tight">
            <button class="sm" @click="startAdd(m)">Новые КБЖУ</button>
            <button class="sm" v-if="(m.variants.find(v => v.is_active)?.version || 1) > 1" @click="rollback(m)">↶ Откат</button>
          </div>
        </div>
        <table class="tbl small">
          <thead><tr><th>Версия</th><th class="r">ккал</th><th class="r">Б</th><th class="r">Ж</th><th class="r">У</th><th></th></tr></thead>
          <tbody>
            <tr v-for="v in sortedVariants(m)" :key="v.id" :style="{ opacity: v.is_active ? 1 : .55 }">
              <td>v{{ v.version }} <span v-if="v.is_active" class="badge ok">активна</span></td>
              <td class="r num">{{ fmt(v.calories, 1) }}</td><td class="r num">{{ fmt(v.proteins, 1) }}</td>
              <td class="r num">{{ fmt(v.fats, 1) }}</td><td class="r num">{{ fmt(v.carbs, 1) }}</td>
              <td><span v-if="v.wrong_nutrients" class="badge warn" title="Калории не сходятся с БЖУ">⚠ проверить</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="adding" class="card stack">
        <h3>{{ adding.isNew ? 'Новый производитель' : 'Новая версия КБЖУ' }}</h3>
        <label class="field" v-if="adding.isNew"><span>Производитель</span><input v-model="adding.manufacturer_name"></label>
        <KbjuInputs v-model="adding.kbju" />
        <div class="row"><button class="primary sm" :disabled="busy" @click="saveVariant">Сохранить</button><button class="sm" @click="adding = null">Отмена</button></div>
        <div class="tiny muted">Рецепты с этим продуктом пересчитаются по новой версии. Приготовленные блюда в холодильнике и съеденное останутся как были.</div>
      </div>
      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot><button v-if="!adding" @click="startAdd(null)">+ Другой производитель</button></template>
    </Modal>`,
};

export const CatalogView = {
  components: { NewProductModal, ProductModal },
  setup() {
    const q = ref("");
    const cat = ref(0);
    const creating = ref(false);
    const opened = ref(null);
    onMounted(() => ensureCatalog().catch(toastError));
    const rows = computed(() => state.products
      .filter((p) => (!cat.value || p.category_id === cat.value) && matches(`${p.name} ${p.brand?.name} ${p.barcode || ""}`, q.value))
      .map((p) => {
        const actives = p.manufacturers.flatMap((m) => m.variants.filter((v) => v.is_active));
        const v = actives[0] || {};
        return { p, v, makers: p.manufacturers.length, warn: actives.some((x) => x.wrong_nutrients) };
      })
      .sort((a, b) => (categoryName.value[a.p.category_id] || "").localeCompare(categoryName.value[b.p.category_id] || "", "ru") || a.p.name.localeCompare(b.p.name, "ru")));
    return { q, cat, creating, opened, rows, state, categoryName, fmt, packagesLabel };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Продукты</h1>
        <button class="primary" @click="creating = true">+ Продукт</button>
      </div>
      <div class="row" style="margin-bottom: 12px">
        <input v-model="q" placeholder="Поиск по названию или бренду…" style="max-width: 320px">
        <select v-model.number="cat" style="max-width: 220px">
          <option :value="0">Все категории</option>
          <option v-for="c in state.productCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <span class="small muted">{{ rows.length }} шт.</span>
      </div>
      <div class="card flush table-wrap">
        <table class="tbl">
          <thead><tr><th>Продукт</th><th>Категория</th><th class="r">ккал</th><th class="r">Б</th><th class="r">Ж</th><th class="r">У</th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.p.id" style="cursor: pointer" @click="opened = r.p">
              <td><b>{{ r.p.name }}</b> <span v-if="r.warn" class="badge warn" title="Калории не сходятся с БЖУ">⚠</span>
                <div class="tiny muted">{{ r.p.brand?.name }}<span v-if="r.makers > 1"> · {{ r.makers }} производителя</span> · {{ packagesLabel(r.p.packages, r.p.base_unit) }}</div></td>
              <td class="small muted">{{ categoryName[r.p.category_id] }}</td>
              <td class="r num">{{ fmt(r.v.calories) }}</td><td class="r num">{{ fmt(r.v.proteins, 1) }}</td>
              <td class="r num">{{ fmt(r.v.fats, 1) }}</td><td class="r num">{{ fmt(r.v.carbs, 1) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!rows.length" class="empty">Ничего не найдено</div>
      </div>
      <NewProductModal v-if="creating" @close="creating = false" @saved="creating = false" />
      <ProductModal v-if="opened" :product="opened" @close="opened = null" />
    </div>`,
};
