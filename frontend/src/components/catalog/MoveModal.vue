<script setup lang="ts">
// Перенести продукт в другой товар (или новый): в покупках и запасах он будет считаться вместе с ним.
import { computed, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { toast } from "../../session";
import ModalSheet from "../ModalSheet.vue";

type Item = Schemas["ItemOut"];
const props = defineProps<{ product: Schemas["ItemProductOut"]; from: Item; items: Item[] }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const target = ref("");
const newName = ref("");
const busy = ref(false);
const error = ref("");
const options = computed(() => props.items.filter((i) => i.key !== props.from.key).sort((a, b) => a.name.localeCompare(b.name, "ru")));
async function save() {
  busy.value = true;
  error.value = "";
  try {
    await ok(api.PUT("/api/v1/items/products/{product_id}", { params: { path: { product_id: props.product.id } },
      body: target.value === "__new" ? { new_name: newName.value.trim() } : { item_key: target.value } }));
    toast("Продукт перенесён");
    emit("saved");
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet :title="'Перенести: ' + product.name" @close="emit('close')">
    <p class="small muted">Сейчас в товаре «{{ from.name }}». В покупках и запасах продукт будет считаться вместе с товаром, куда перенесёте.</p>
    <label class="field"><span class="lbl">В товар</span>
      <select v-model="target">
        <option value="" disabled>— выберите —</option>
        <option value="__new">+ Новый товар…</option>
        <option v-for="i in options" :key="i.key" :value="i.key">{{ i.name }}</option>
      </select></label>
    <label v-if="target === '__new'" class="field"><span class="lbl">Название нового товара</span><input v-model="newName" placeholder="Кефир 1%"></label>
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy || !target || (target === '__new' && !newName.trim())" @click="save">Перенести</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.err { color: var(--tomato); }
</style>
