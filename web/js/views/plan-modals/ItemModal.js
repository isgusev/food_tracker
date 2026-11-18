import { ref, computed, watch } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, Macros } from "../../components.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError, activeVariantOf } from "../../product-finder.js";
import {
  state, toast, variantIndex, recipeById, recipeCategoryName, activeMembers, memberById,
} from "../../store.js";
import { MEALS, MEAL_LABEL, bjuLine, fmt, fmtQty, grams, local, n, packageGrams, fmtWeekday, fmtDayMonth } from "../../util.js";

// ---------- помощники для отображения блюда ----------
import { itemBadge } from "./shared.js";

// ---------- карточка блюда ----------
export const ItemModal = {
  components: { Modal, Macros },
  props: { item: Object },
  emits: ["close", "changed"],
  setup(props, { emit }) {
    const it = ref(props.item);
    const weights = ref({});
    const resetWeights = () => { weights.value = Object.fromEntries(it.value.portions.map((p) => [p.id, n(p.weight_g)])); };
    resetWeights();
    const moveDate = ref(it.value.date_day);
    const moveMeal = ref(it.value.meal_type);
    const addWho = ref("");
    const addWeight = ref(n(it.value.portions[0]?.weight_g) || 200);

    const { busy, error, run } = useAction({
      inline: true,
      done: (res) => { if (res) { it.value = res; resetWeights(); } emit("changed", res || null); },
    });
    const changed = (p) => n(weights.value[p.id]) !== n(p.weight_g);
    const eat = (p) => run(() => api.post(`/plan/portions/${p.id}/eat`, { weight_g: n(weights.value[p.id]) }), `${p.member_name || "Гость"}: съедено`);
    const uneat = (p) => run(() => api.post(`/plan/portions/${p.id}/uneat`), "Отметка снята");
    const detach = (p) => run(() => api.post(`/plan/portions/${p.id}/detach`), "Отвязано от холодильника");
    const saveWeight = (p) => run(() => api.patch(`/plan/portions/${p.id}`, { weight_g: n(weights.value[p.id]) }), "Порция обновлена");
    async function removePortion(p) {
      const last = it.value.portions.length === 1;
      if (last && !confirm("Это последняя порция — блюдо будет удалено из плана. Продолжить?")) return;
      const res = await run(() => api.del(`/plan/portions/${p.id}`), last ? "Блюдо удалено" : "Порция убрана");
      if (last && !error.value) emit("close");
      return res;
    }
    const eatAll = () => run(() => api.post(`/plan/${it.value.id}/eat`), "Отмечено: все поели");
    const move = () => run(() => api.patch(`/plan/${it.value.id}`, { date_day: moveDate.value, meal_type: moveMeal.value }), "Перенесено");
    async function removeItem() {
      const fromPot = it.value.portions.some((p) => p.is_eaten && p.eaten_from_pot_id);
      if (!confirm(`Удалить «${it.value.name}» из плана?${fromPot ? "\nСъеденное вернётся в кастрюлю." : ""}`)) return;
      await run(() => api.del(`/plan/${it.value.id}`), "Удалено");
      if (!error.value) emit("close");
    }
    const missing = computed(() => activeMembers.value.filter((m) => !it.value.portions.some((p) => p.member_id === m.id)));
    function addPortion() {
      const member_id = addWho.value === "guest" ? null : Number(addWho.value);
      return run(() => api.post(`/plan/${it.value.id}/portions`, { member_id, weight_g: n(addWeight.value) }), "Порция добавлена")
        .then(() => { addWho.value = ""; });
    }
    const acceptIt = () => run(() => api.post(`/plan/${it.value.id}/accept`), "Принято");
    const pinToggle = () => run(() => api.patch(`/plan/${it.value.id}`, { pinned: !it.value.pinned }), it.value.pinned ? "Откреплено" : "Закреплено");
    const alternative = () => run(() => api.post(`/plan/${it.value.id}/alternative`), "Другой вариант");
    const canSwap = computed(() => it.value.kind === "recipe" && !it.value.cooking_log_id && !it.value.portions.some((p) => p.is_eaten));
    const badge = computed(() => itemBadge(it.value));
    const uneaten = computed(() => it.value.portions.filter((p) => !p.is_eaten).length);
    return {
      it, weights, busy, error, moveDate, moveMeal, addWho, addWeight, missing, badge, uneaten, MEALS, MEAL_LABEL,
      acceptIt, pinToggle, alternative, canSwap,
      changed, eat, uneat, detach, saveWeight, removePortion, eatAll, move, removeItem, addPortion,
      grams, fmt, fmtWeekday, fmtDayMonth, memberById,
    };
  },
  template: `
    <Modal :title="it.name" wide @close="$emit('close')">
      <div class="row">
        <span class="badge" :class="badge.cls">{{ badge.text }}</span>
        <span class="muted small">{{ MEAL_LABEL[it.meal_type] }} · {{ fmtWeekday(it.date_day) }} {{ fmtDayMonth(it.date_day) }}</span>
        <span class="muted small" v-if="it.fridge_pot_id">· в кастрюле {{ grams(it.fridge_available_g) }}</span>
      </div>
      <div v-if="it.origin === 'auto'" class="draft-bar" style="margin: 0">
        <span class="draft-swatch" aria-hidden="true"></span>
        <div class="grow small">Предложено планировщиком<template v-if="it.auto_reason">: <i>{{ it.auto_reason }}</i></template>.
          <div class="tiny muted">Поправите порции или перенесёте — станет обычным блюдом.</div></div>
        <button class="sm ghost" :disabled="busy" @click="pinToggle" :title="it.pinned ? 'Открепить' : 'Новый подбор не заменит'">{{ it.pinned ? '📌 Открепить' : '📌 Закрепить' }}</button>
        <button v-if="canSwap" class="sm ghost" :disabled="busy" @click="alternative">🔄 Другое</button>
        <button class="sm primary" :disabled="busy" @click="acceptIt">✓ Принять</button>
      </div>

      <div class="card flush table-wrap">
        <table class="tbl">
          <thead><tr><th>Кто</th><th class="r">Порция, г</th><th class="r">ккал</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            <tr v-for="p in it.portions" :key="p.id">
              <td><b v-if="p.member_id">{{ p.member_name }}</b><span v-else class="muted">Гость</span></td>
              <td class="r"><input type="number" min="1" max="2000" step="any" v-model="weights[p.id]" style="width: 84px"
                     @keydown.enter="p.is_eaten ? saveWeight(p) : eat(p)"></td>
              <td class="r num">{{ fmt(p.calories) }}</td>
              <td>
                <span v-if="p.is_eaten" class="badge ok">✓ съел{{ p.eaten_from_pot_id ? ' · из холодильника' : '' }}</span>
                <span v-else class="badge">в плане</span>
              </td>
              <td class="r nowrap">
                <button v-if="changed(p)" class="sm" :disabled="busy" @click="saveWeight(p)">Сохранить</button>
                <button v-if="!p.is_eaten" class="sm primary" :disabled="busy" @click="eat(p)" title="Съедено (вес — из поля)">✓ Съел</button>
                <button v-else class="sm ghost" :disabled="busy" @click="uneat(p)" title="Отменить «съедено»">↺</button>
                <button v-if="p.is_eaten && p.eaten_from_pot_id" class="sm ghost" :disabled="busy" @click="detach(p)"
                        title="Ели не из этой кастрюли — вес в неё не вернётся">без холодильника</button>
                <button class="sm ghost" :disabled="busy" @click="removePortion(p)" title="Убрать порцию">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="row">
        <select v-model="addWho" style="max-width: 200px">
          <option value="">+ Добавить едока…</option>
          <option v-for="m in missing" :key="m.id" :value="m.id">{{ m.name }}</option>
          <option value="guest">Гость</option>
        </select>
        <template v-if="addWho">
          <input type="number" min="1" max="2000" step="any" v-model="addWeight" style="width: 90px"><span class="small muted">г</span>
          <button class="sm" :disabled="busy" @click="addPortion">Добавить</button>
        </template>
      </div>

      <details>
        <summary class="small muted" style="cursor: pointer">Перенести на другой день / приём пищи</summary>
        <div class="row" style="margin-top: 8px">
          <input type="date" v-model="moveDate" style="width: 170px">
          <select v-model="moveMeal" style="width: 140px"><option v-for="m in MEALS" :key="m.key" :value="m.key">{{ m.label }}</option></select>
          <button class="sm" :disabled="busy" @click="move">Перенести</button>
        </div>
      </details>

      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button class="danger" :disabled="busy" @click="removeItem">Удалить блюдо</button>
        <span class="grow"></span>
        <button v-if="uneaten" class="primary" :disabled="busy" @click="eatAll">✓ Все поели</button>
      </template>
    </Modal>`,
};
