// Справочник продуктов: КБЖУ с версиями по производителям.
import { ref, computed, watch, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Macros, BarcodeScanner, KbjuInputs } from "../components.js";
import { state, ensureCatalog, loadProducts, categoryName, variantIndex, toast, toastError } from "../store.js";
import { fmt, fuzzyScore, matches, n, packagesLabel } from "../util.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../product-finder.js";

// Новый продукт — тот же поиск, что при добавлении в план: справочник → штрихкод/📷 →
// Open Food Facts → «ввести вручную»; найденное или введённое проверяется в карточке
const NewProductModal = {
  components: { Modal, ProductFinder, OffDraftCard },
  emits: ["close", "saved", "open"],
  setup(_, { emit }) {
    const variantId = ref(null);
    const draft = ref(null);
    const busy = ref(false);
    const error = ref("");
    // выбрали продукт, который уже есть в справочнике, — открываем его карточку
    watch(variantId, (id) => {
      const v = id && variantIndex.value[id];
      if (v) emit("open", v.product);
    });
    async function save() {
      error.value = "";
      if (!draft.value) { error.value = "Найдите продукт или нажмите «Ввести вручную»"; return; }
      if ((error.value = draftError(draft.value))) return;
      busy.value = true;
      try {
        await saveDraft(draft.value, { reuse: false });
        toast(`«${draft.value.name.trim()}» добавлен`);
        emit("saved");
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    return { variantId, draft, busy, error, save };
  },
  template: `
    <Modal title="Новый продукт" @close="$emit('close')">
      <div class="field"><span>Продукт</span>
        <ProductFinder v-model="variantId" v-model:draft="draft" autofocus />
        <span v-if="!draft" class="tiny muted">Название, бренд или штрихкод (📷 — камерой). Не нашли у нас — ищем в Open Food Facts; нет и там — «Ввести вручную».</span>
      </div>
      <OffDraftCard v-if="draft" :draft="draft" />
      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy || !draft" @click="save">Сохранить</button>
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
      .filter((p) => (!cat.value || p.category_id === cat.value) && (matches(`${p.name} ${p.brand?.name} ${p.barcode || ""}`, q.value) || fuzzyScore(q.value, `${p.name} ${p.brand?.name}`) >= 0.6))
      .map((p) => {
        const actives = p.manufacturers.flatMap((m) => m.variants.filter((v) => v.is_active));
        const v = actives[0] || {};
        return { p, v, makers: p.manufacturers.length, warn: actives.some((x) => x.wrong_nutrients) };
      })
      .sort((a, b) => (categoryName.value[a.p.category_id] || "").localeCompare(categoryName.value[b.p.category_id] || "", "ru") || a.p.name.localeCompare(b.p.name, "ru")));
    return { q, cat, creating, opened, rows, state, categoryName, fmt, packagesLabel, toast };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Продукты</h1>
        <button class="primary" @click="creating = true">+ Продукт</button>
      </div>
      <div class="row" style="margin-bottom: 12px">
        <div class="clearable" style="max-width: 320px">
          <input v-model="q" placeholder="Поиск по названию, бренду, штрихкоду…">
          <button v-if="q" type="button" class="clear-btn" aria-label="Очистить" title="Очистить" @click="q = ''">✕</button>
        </div>
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
      <NewProductModal v-if="creating" @close="creating = false" @saved="creating = false"
        @open="(p) => { creating = false; opened = p; toast('Этот продукт уже есть в справочнике'); }" />
      <ProductModal v-if="opened" :product="opened" @close="opened = null" />
    </div>`,
};
