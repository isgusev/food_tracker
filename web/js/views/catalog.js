// Справочник продуктов: КБЖУ с версиями по производителям.
import { ref, computed, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Macros } from "../components.js";
import { state, ensureCatalog, loadProducts, categoryName, toast, toastError } from "../store.js";
import { fmt, matches, n } from "../util.js";

// То же правило, что на сервере (app/domain.py): ошибка — если расхождение > 10 ккал И > 15 %
function atwater(k) {
  const calc = 4 * n(k.proteins) + 9 * n(k.fats) + 4 * n(k.carbs);
  const diff = Math.abs(n(k.calories) - calc);
  return { calc, off: n(k.calories) > 0 && diff > 10 && diff > 0.15 * calc };
}

const KbjuInputs = {
  props: { modelValue: Object },
  setup(props) { return { check: computed(() => atwater(props.modelValue)), fmt }; },
  template: `
    <div class="stack tight">
      <div class="grid-4">
        <label class="field"><span>Ккал / 100 г</span><input type="number" min="0" step="any" v-model="modelValue.calories"></label>
        <label class="field"><span>Белки, г</span><input type="number" min="0" step="any" v-model="modelValue.proteins"></label>
        <label class="field"><span>Жиры, г</span><input type="number" min="0" step="any" v-model="modelValue.fats"></label>
        <label class="field"><span>Углеводы, г</span><input type="number" min="0" step="any" v-model="modelValue.carbs"></label>
      </div>
      <div v-if="check.off" class="tiny" style="color: var(--warn)">
        По БЖУ выходит ≈ {{ fmt(check.calc) }} ккал — проверьте цифры с упаковки (сохранить можно, версия будет помечена).
      </div>
    </div>`,
};

const NewProductModal = {
  components: { Modal, KbjuInputs },
  emits: ["close", "saved"],
  setup(_, { emit }) {
    const f = ref({ name: "", category: "", brand: "", manufacturer: "", kbju: { calories: "", proteins: "", fats: "", carbs: "" } });
    const busy = ref(false);
    const error = ref("");
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
    return { f, busy, error, save, state };
  },
  template: `
    <Modal title="Новый продукт" @close="$emit('close')">
      <label class="field"><span>Название</span><input v-model="f.name" placeholder="Йогурт греческий 2%"></label>
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
  components: { Modal, KbjuInputs, Macros },
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
    return { p, adding, busy, error, startAdd, saveVariant, rollback, sortedVariants, categoryName, fmt };
  },
  template: `
    <Modal :title="p.name" wide @close="$emit('close')">
      <div class="row small muted"><span class="badge">{{ categoryName[p.category_id] }}</span><span>Бренд: {{ p.brand?.name }}</span></div>
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
      .filter((p) => (!cat.value || p.category_id === cat.value) && matches(`${p.name} ${p.brand?.name}`, q.value))
      .map((p) => {
        const actives = p.manufacturers.flatMap((m) => m.variants.filter((v) => v.is_active));
        const v = actives[0] || {};
        return { p, v, makers: p.manufacturers.length, warn: actives.some((x) => x.wrong_nutrients) };
      })
      .sort((a, b) => (categoryName.value[a.p.category_id] || "").localeCompare(categoryName.value[b.p.category_id] || "", "ru") || a.p.name.localeCompare(b.p.name, "ru")));
    return { q, cat, creating, opened, rows, state, categoryName, fmt };
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
                <div class="tiny muted">{{ r.p.brand?.name }}<span v-if="r.makers > 1"> · {{ r.makers }} производителя</span></div></td>
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
