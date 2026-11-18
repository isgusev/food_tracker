import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Macros, BarcodeScanner, KbjuInputs } from "../../components.js";
import { state, ensureCatalog, loadProducts, categoryName, variantIndex, toast, toastError } from "../../store.js";
import { fmt, fuzzyScore, local, matches, n, packagesLabel } from "../../util.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../../product-finder.js";
import { ItemsPanel } from "../items.js";

// Новый продукт — тот же поиск, что при добавлении в план: справочник → штрихкод/📷 →
// Open Food Facts → «ввести вручную»; найденное или введённое проверяется в карточке
import { NewProductModal } from "./NewProductModal.js";
import { ProductModal } from "./ProductModal.js";

export const CatalogView = {
  components: { NewProductModal, ProductModal, ItemsPanel },
  setup() {
    const tab = ref(local.get("ft.catalogTab", "products"));   // products | items
    const setTab = (t) => { tab.value = t; local.set("ft.catalogTab", t); };
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
    return { tab, setTab, q, cat, creating, opened, rows, state, categoryName, fmt, packagesLabel, toast };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Продукты</h1>
        <button class="primary" @click="creating = true">+ Продукт</button>
      </div>
      <div class="segmented" style="margin-bottom: 12px">
        <button :class="{ on: tab === 'products' }" @click="setTab('products')">Продукты</button>
        <button :class="{ on: tab === 'items' }" @click="setTab('items')">Товары</button>
      </div>
      <ItemsPanel v-if="tab === 'items'" />
      <template v-else>
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
                <span v-if="r.p.kbju_missing" class="badge warn" title="Продукт добавлен из чека или покупок — внесите КБЖУ: откройте его и нажмите «Новые КБЖУ»">нет КБЖУ</span>
                <div class="tiny muted"><span v-if="r.p.item && r.p.item.name !== r.p.name">{{ r.p.item.name }} · </span>{{ r.p.brand?.name }}<span v-if="r.makers > 1"> · {{ r.makers }} производителя</span> · {{ packagesLabel(r.p.packages, r.p.base_unit) }}</div></td>
              <td class="small muted">{{ categoryName[r.p.category_id] }}</td>
              <td class="r num">{{ fmt(r.v.calories) }}</td><td class="r num">{{ fmt(r.v.proteins, 1) }}</td>
              <td class="r num">{{ fmt(r.v.fats, 1) }}</td><td class="r num">{{ fmt(r.v.carbs, 1) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!rows.length" class="empty">Ничего не найдено</div>
      </div>
      </template>
      <NewProductModal v-if="creating" @close="creating = false" @saved="creating = false"
        @open="(p) => { creating = false; opened = p; toast('Этот продукт уже есть в справочнике'); }" />
      <ProductModal v-if="opened" :product="opened" @close="opened = null" />
    </div>`,
};
