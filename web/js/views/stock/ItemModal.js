import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, BarcodeScanner } from "../../components.js";
import { state, ensureCatalog, toast, toastError } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, matches, n, today, UNIT_LABEL } from "../../util.js";
import { PacksEditor, packsBody, defaultPackAmount, productById } from "../../marking.js";
import { REASON } from "./shared.js";
import { SplitLotModal } from "./SplitLotModal.js";

export const ItemModal = {
  components: { Modal, SplitLotModal },
  props: { item: Object },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const it = ref(props.item);
    const actual = ref(n(props.item.remaining));
    const woQty = ref("");
    const woNote = ref("");
    const history = ref([]);
    const splitting = ref(null);   // партия, которую раскладываем по пачкам
    onMounted(async () => {
      try { history.value = await api.get(`/stock/items/${it.value.product_id}/history`); } catch { /* необязательно */ }
    });
    const { busy, run } = useAction({
      done: async (list) => {
        emit("saved", list);
        it.value = list.find((x) => x.item_key === it.value.item_key) || { ...it.value, remaining: 0, lots: [] };
        history.value = await api.get(`/stock/items/${it.value.product_id}/history`);
      },
    });
    const inventory = () => run(() => api.post(`/stock/items/${it.value.product_id}/inventory`, { quantity: n(actual.value) }), "Остаток уточнён");
    const writeOff = () => n(woQty.value) > 0 && run(() => api.post(`/stock/items/${it.value.product_id}/write-off`, { quantity: n(woQty.value), note: woNote.value || null }), "Списано");
    const flags = (body, msg) => run(() => api.patch(`/stock/items/${it.value.product_id}`, body), msg);
    function onSplit(list) {
      splitting.value = null;
      emit("saved", list);
      it.value = list.find((x) => x.item_key === it.value.item_key) || it.value;
    }
    // ближайший срок — сверху: так же холодильник и списывает
    const lotsByExpiry = computed(() => [...it.value.lots].sort((x, y) => (x.expires_on || "9999").localeCompare(y.expires_on || "9999") || x.id - y.id));
    const regQty = ref(props.item.regular_qty == null ? "" : n(props.item.regular_qty));
    const REGULAR = [
      { key: "auto", label: "Как обычно", msg: "Решает статистика покупок" },
      { key: "always", label: "Всегда предлагать", msg: "Будем предлагать каждую неделю" },
      { key: "never", label: "Не предлагать", msg: "Больше не предлагаем" },
    ];
    return { regQty, REGULAR, it, actual, woQty, woNote, history, busy, inventory, writeOff, flags, splitting, onSplit, lotsByExpiry, todayIso: today(), fmt, fmtQty, fmtDayMonth, fmtDateTime, REASON, UNIT_LABEL, n };
  },
  template: `
    <Modal :title="it.name" wide @close="$emit('close')">
      <div class="row">
        <span class="badge" v-if="it.is_staple">базовый — остаток не считаем</span>
        <span class="badge warn" v-if="it.needs_check">учёт сбился — уточните остаток</span>
        <span class="badge danger" v-if="n(it.expired) > 0">просрочено {{ fmtQty(it.expired, it.unit) }}</span>
        <span class="muted small" v-if="!it.is_staple">Сейчас: <b class="num">{{ fmtQty(it.remaining, it.unit) }}</b></span>
      </div>

      <div v-if="it.lots.length" class="card flush">
        <div v-for="l in lotsByExpiry" :key="l.id" class="lot-row">
          <div class="grow" style="min-width: 0">
            <div><b :class="{ 'lot-expired': l.expires_on && l.expires_on < todayIso }">{{ l.expires_on ? 'до ' + fmtDayMonth(l.expires_on) : 'срок не указан' }}</b>
              · <span class="num">{{ fmtQty(l.remaining, it.unit) }}</span><span class="muted small"> из {{ fmtQty(l.quantity, it.unit) }}</span></div>
            <div class="tiny muted ellipsis">{{ fmtDayMonth(l.purchased_on) }} · {{ l.brand || '—' }} · {{ REASON[l.source] || l.source }}<template v-if="l.price != null"> · {{ fmt(l.price, 2) }} ₽</template></div>
          </div>
          <button class="sm" @click="splitting = l" title="Указать сроки по пачкам (код «Честного знака»)">📦 Сроки</button>
        </div>
      </div>

      <div class="grid-2" v-if="!it.is_staple">
        <div class="card stack">
          <h3>Уточнить остаток</h3>
          <div class="row"><input type="number" min="0" step="any" v-model="actual" style="width: 120px"><span class="muted small">{{ UNIT_LABEL[it.unit] }}</span>
            <button class="sm primary" :disabled="busy" @click="inventory">Так и есть</button></div>
          <span class="tiny muted">Пересчитали дома — запасы станут ровно такими.</span>
        </div>
        <div class="card stack">
          <h3>Списать</h3>
          <div class="row"><input type="number" min="0.1" step="any" v-model="woQty" style="width: 110px" placeholder="сколько">
            <input v-model="woNote" placeholder="испортилось…" style="flex: 1; min-width: 100px"></div>
          <div><button class="sm danger" :disabled="busy || !woQty" @click="writeOff">Списать</button></div>
        </div>
      </div>

      <div class="row">
        <button class="sm" :disabled="busy" @click="flags({ is_staple: !it.is_staple }, it.is_staple ? 'Снова учитываем остаток' : 'Теперь базовый')">{{ it.is_staple ? 'Учитывать остаток' : 'Сделать базовым' }}</button>
        <button v-if="it.is_staple" class="sm" :disabled="busy" @click="flags({ is_low: !it.is_low }, it.is_low ? 'Отметка снята' : 'Добавится в покупки')">{{ it.is_low ? 'Хватает' : 'Заканчивается' }}</button>
        <span class="tiny muted">Базовые (соль, масло, специи) не считаются по граммам — в покупки попадают по отметке «заканчивается».</span>
      </div>

      <div class="card stack" v-if="!it.is_staple">
        <h3>Обычно берём</h3>
        <div class="row tight">
          <button v-for="o in REGULAR" :key="o.key" class="sm chip" :class="{ on: it.regular === o.key }" :aria-pressed="it.regular === o.key"
                  :disabled="busy" @click="flags({ regular: o.key }, o.msg)">{{ o.label }}</button>
        </div>
        <div class="row">
          <span class="small">В неделю</span>
          <input type="number" min="0" step="any" v-model="regQty" style="width: 100px" :placeholder="'как обычно'">
          <span class="muted small">{{ UNIT_LABEL[it.unit] }}</span>
          <button class="sm" :disabled="busy || n(regQty) === n(it.regular_qty)" @click="flags({ regular_qty: regQty === '' ? null : n(regQty) }, 'Количество сохранено')">Сохранить</button>
        </div>
        <label class="row small"><input type="checkbox" :checked="it.is_snack" :disabled="busy"
               @change="flags({ is_snack: $event.target.checked }, $event.target.checked ? 'Считаем в квоту снеков' : 'Не снек')"> Снек или сладкое — считать в квоту</label>
        <span class="tiny muted">«Как обычно» — по покупкам: брали в 4 из 8 последних недель — предложим в «Покупках». Пусто в «В неделю» — медиана покупок.</span>
      </div>

      <SplitLotModal v-if="splitting" :lot="splitting" :unit="it.unit" @close="splitting = null" @saved="onSplit" />
      <details v-if="history.length">
        <summary class="small muted" style="cursor: pointer">История ({{ history.length }})</summary>
        <div class="stack tight" style="margin-top: 8px">
          <div v-for="m in history" :key="m.id" class="row between small">
            <span>{{ fmtDateTime(m.created_at) }} · {{ REASON[m.reason] || m.reason }}<span v-if="m.note" class="muted"> · {{ m.note }}</span></span>
            <b class="num" :style="{ color: n(m.delta) < 0 ? 'var(--danger)' : 'var(--accent)' }">{{ n(m.delta) > 0 ? '+' : '' }}{{ fmtQty(m.delta, it.unit) }}</b>
          </div>
        </div>
      </details>
    </Modal>`,
};
