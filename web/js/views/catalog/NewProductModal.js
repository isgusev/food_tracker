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

export const NewProductModal = {
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
