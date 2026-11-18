import { ref, computed, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { Modal } from "../../components.js";
import { loadProducts, toast, toastError } from "../../store.js";
import { fmtQty, fuzzyScore, local } from "../../util.js";

// Перенести продукт в другой товар или выделить в новый
export const MoveModal = {
  components: { Modal },
  props: { product: Object, from: Object, items: Array },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const target = ref("");
    const newName = ref("");
    const busy = ref(false);
    const options = computed(() => props.items.filter((i) => i.key !== props.from.key));
    async function save() {
      busy.value = true;
      try {
        await api.put(`/items/products/${props.product.id}`, target.value === "__new" ? { new_name: newName.value } : { item_key: target.value });
        toast("Продукт перенесён");
        emit("saved");
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { target, newName, busy, options, save };
  },
  template: `
    <Modal :title="'Перенести: ' + product.name" @close="$emit('close')">
      <div class="small muted">Сейчас в товаре «{{ from.name }}». В покупках и запасах продукт будет считаться вместе с товаром, куда перенесёте.</div>
      <label class="field"><span>В товар</span>
        <select v-model="target">
          <option value="" disabled>— выберите —</option>
          <option value="__new">+ Новый товар…</option>
          <option v-for="i in options" :key="i.key" :value="i.key">{{ i.name }}</option>
        </select></label>
      <label v-if="target === '__new'" class="field"><span>Название нового товара</span><input v-model="newName" placeholder="Кефир 1%"></label>
      <template #foot><button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy || !target || (target === '__new' && !newName.trim())" @click="save">Перенести</button></template>
    </Modal>`,
};
