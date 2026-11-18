import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Macros, MacroMeters, Modal } from "../../components.js";
import {
  state, ensureCatalog, toast, toastError, activeMembers, members, viewMember, setViewMember,
  targetsForMeters, hasTargets,
} from "../../store.js";
import {
  MEALS, MEAL_ORDER, addDays, fmt, fmtDayMonth, fmtDayMonthLong, fmtWeekday, fmtWeekdayLong,
  grams, local, n, range, startOfWeek, today,
} from "../../util.js";

import {
  AddItemModal, ItemModal, allEaten, itemBadge, itemIcon, memberMacros, portionOf, portionsSummary,
} from "../plan-modals.js";

// Шаблоны недель: сохранить текущую неделю и применить сохранённую
export const TemplatesModal = {
  components: { Modal },
  props: { weekStart: String },
  emits: ["close", "applied"],
  setup(props, { emit }) {
    const list = ref([]);
    const name = ref("");
    const busy = ref(false);
    const load = () => api.get("/plan/templates").then((r) => { list.value = r; }).catch(toastError);
    onMounted(load);
    async function save() {
      if (!name.value.trim()) return;
      busy.value = true;
      try {
        await api.post("/plan/templates", { name: name.value.trim(), week_start: props.weekStart });
        name.value = "";
        toast("Неделя сохранена как шаблон");
        await load();
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    async function apply(t) {
      busy.value = true;
      try {
        const r = await api.post(`/plan/templates/${t.id}/apply`, { week_start: props.weekStart });
        toast(`Добавлено блюд: ${r.created}` + (r.skipped ? `, пропущено ${r.skipped} (рецепт удалён или едок скрыт)` : ""));
        emit("applied");
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    async function remove(t) {
      if (!confirm(`Удалить шаблон «${t.name}»?`)) return;
      try { await api.del(`/plan/templates/${t.id}`); await load(); } catch (e) { toastError(e); }
    }
    const days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
    return { list, name, busy, save, apply, remove, days, fmtDayMonth };
  },
  template: `
    <Modal title="Шаблоны недель" @close="$emit('close')">
      <div class="row">
        <input v-model="name" placeholder="Название, например «Обычная неделя»" style="flex: 1; min-width: 180px" @keydown.enter="save">
        <button class="primary sm" :disabled="busy || !name.trim()" @click="save">Сохранить эту неделю</button>
      </div>
      <div class="tiny muted">Сохраняются блюда и порции каждого. Применение добавляет блюда к неделе с {{ fmtDayMonth(weekStart) }} — то, что уже запланировано, остаётся.</div>
      <div v-if="!list.length" class="empty">Шаблонов пока нет</div>
      <div v-else class="card flush">
        <div v-for="t in list" :key="t.id" class="list-item">
          <div class="grow"><b>{{ t.name }}</b>
            <div class="tiny muted">{{ t.items_count }} блюд · <span v-for="(d, i) in days" :key="i">{{ d }} {{ t.meals_per_day[i] || 0 }}{{ i < 6 ? ', ' : '' }}</span></div></div>
          <button class="sm primary" :disabled="busy" @click="apply(t)">Применить</button>
          <button class="sm ghost" @click="remove(t)" title="Удалить">✕</button>
        </div>
      </div>
    </Modal>`,
};
