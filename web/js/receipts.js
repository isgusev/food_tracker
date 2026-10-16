// Чек по QR: строка QR → расшифровка (code-qr.ru → ФНС) → сопоставление строк чека
// со списком покупок и справочником → проверка → «Сохранить покупки».
// Чек доходит до налоговой с задержкой: «ждём» — нормальное состояние, чек сохранён.
import { ref, computed, onMounted } from "../vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { Modal, Picker, BarcodeScanner } from "./components.js";
import { state, toast, toastError } from "./store.js";
import { fmt, fmtDateTime, fmtQty, n, UNIT_LABEL } from "./util.js";

const SOURCE = { alias: "запомнено", list: "из списка", catalog: "похоже", none: "" };

// Строка чека → редактируемое решение: choice = "skip" | "line:<id>" | "product"
function rowFrom(item, lines) {
  const s = item.suggestion || { action: "skip", source: "none" };
  let choice = "skip";
  if (s.action === "list" && s.shopping_line_id && lines.some((l) => l.id === s.shopping_line_id)) choice = `line:${s.shopping_line_id}`;
  else if (s.action !== "skip" && s.product_id) choice = "product";
  return {
    index: item.index, item, source: s.source, confidence: s.confidence || 0,
    choice, product_id: s.product_id || null,
    quantity: s.quantity != null ? n(s.quantity) : "", qtyEdited: false,
  };
}

export const ReceiptModal = {
  components: { Modal, Picker, BarcodeScanner },
  emits: ["close", "applied"],
  setup(_, { emit }) {
    const receipt = ref(null);
    const recent = ref([]);
    const lines = ref([]);          // неотмеченные строки активного списка
    const rows = ref([]);
    const qr = ref("");
    const scanning = ref(false);
    const busy = ref(false);
    const error = ref("");

    async function loadContext() {
      try { recent.value = await api.get("/receipts"); } catch { /* не критично */ }
      try {
        const lst = await api.get("/shopping-lists/active");
        lines.value = (lst?.lines || []).filter((l) => !l.is_checked);
      } catch { lines.value = []; }
    }
    onMounted(loadContext);

    function show(r) {
      receipt.value = r;
      rows.value = r.status === "done" ? r.items.map((it) => rowFrom(it, lines.value)) : [];
    }
    async function submit(text) {
      scanning.value = false;
      const q = (text ?? qr.value).trim();
      if (q.length < 10) { error.value = "Отсканируйте QR-код чека или вставьте строку из него"; return; }
      error.value = ""; busy.value = true;
      try { show(await api.post("/receipts", { qr: q })); }
      catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    async function open(id) {
      error.value = ""; busy.value = true;
      try { show(await api.get(`/receipts/${id}`)); }
      catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    const refresh = () => open(receipt.value.id);
    function back() { receipt.value = null; error.value = ""; loadContext(); }

    const productItems = computed(() => state.products.map((p) => ({ id: p.id, label: p.name, sub: p.brand?.name })));
    const lineById = computed(() => Object.fromEntries(lines.value.map((l) => [l.id, l])));
    function unitOf(r) {
      if (r.choice.startsWith("line:")) return lineById.value[Number(r.choice.slice(5))]?.unit || "g";
      return state.products.find((p) => p.id === r.product_id)?.base_unit || r.item.suggestion?.unit || "g";
    }
    // одна строка списка — одной строке чека
    const usedLines = computed(() => new Set(rows.value.filter((r) => r.choice.startsWith("line:")).map((r) => r.choice)));
    const chosen = computed(() => rows.value.filter((r) => r.choice !== "skip"));
    const chosenSum = computed(() => chosen.value.reduce((s, r) => s + n(r.item.sum), 0));

    async function apply() {
      error.value = "";
      const body = rows.value.map((r) => {
        if (r.choice === "skip") return { index: r.index, action: "skip" };
        const line = { index: r.index, price: n(r.item.sum) };
        if (r.qtyEdited && n(r.quantity) > 0) line.quantity = n(r.quantity);
        if (r.choice.startsWith("line:")) return { ...line, action: "list", shopping_line_id: Number(r.choice.slice(5)) };
        return { ...line, action: "extra", product_id: r.product_id };
      });
      const noProduct = rows.value.find((r) => r.choice === "product" && !r.product_id);
      if (noProduct) { error.value = `Выберите продукт для «${noProduct.item.name}» или пропустите строку`; return; }
      busy.value = true;
      try {
        await api.post(`/receipts/${receipt.value.id}/apply`, { lines: body });
        toast(`Чек сохранён, покупок: ${chosen.value.length}`);
        emit("applied");
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    return {
      receipt, recent, lines, rows, qr, scanning, busy, error, submit, open, refresh, apply, back,
      productItems, lineById, unitOf, usedLines, chosen, chosenSum, SOURCE, fmt, fmtDateTime, fmtQty, n, UNIT_LABEL,
    };
  },
  template: `
    <Modal title="Чек по QR-коду" wide @close="$emit('close')">
      <template v-if="!receipt">
        <div class="row">
          <button class="primary" @click="scanning = true">📷 Сканировать QR чека</button>
        </div>
        <div class="field"><span>…или строка из QR-кода</span>
          <div class="row" style="flex-wrap: nowrap">
            <input v-model="qr" placeholder="t=20261015T2145&s=100.63&fn=…&i=…&fp=…&n=1" @keydown.enter="submit()">
            <button :disabled="busy" @click="submit()">Загрузить</button>
          </div>
        </div>
        <div v-if="recent.length" class="stack tight">
          <div class="picker-group">Недавние чеки</div>
          <div v-for="r in recent" :key="r.id" class="picker-item" @click="open(r.id)">
            <span class="grow" style="min-width: 0"><span>{{ r.store_name || 'Чек' }}</span>
              <span class="tiny muted" style="display: block">{{ r.purchased_at ? fmtDateTime(r.purchased_at) : '' }} · {{ r.items_count }} поз.</span></span>
            <span class="finder-right"><span>{{ r.total != null ? fmt(r.total, 2) + ' ₽' : '' }}</span>
              <span class="tiny">{{ { pending: 'ждём ФНС', done: 'проверить', error: 'ошибка', applied: 'сохранён' }[r.status] }}</span></span>
          </div>
        </div>
        <div class="tiny muted">Строки чека сопоставятся со списком покупок и справочником; вы проверите и поправите перед сохранением. Сопоставления запоминаются — следующие чеки из того же магазина узнаются сами.</div>
      </template>

      <template v-else>
        <div class="row small">
          <b>{{ receipt.store_name || 'Чек' }}</b>
          <span class="muted">{{ receipt.purchased_at ? fmtDateTime(receipt.purchased_at) : '' }}</span>
          <span class="grow"></span>
          <b class="num">{{ receipt.total != null ? fmt(receipt.total, 2) + ' ₽' : '' }}</b>
        </div>
        <div v-if="receipt.status === 'pending'" class="alert info">
          Чек ещё не дошёл до налоговой — обычно это минуты, иногда несколько часов. Он сохранён:
          откройте его позже из «Недавних чеков». <button class="sm" :disabled="busy" @click="refresh">Проверить снова</button>
        </div>
        <div v-else-if="receipt.status === 'error'" class="alert error">{{ receipt.error || 'Сервис не смог расшифровать чек' }}</div>
        <div v-else-if="receipt.status === 'applied'" class="alert info">Этот чек уже сохранён в покупки.</div>

        <div v-if="receipt.status === 'done'" class="stack tight">
          <div v-for="r in rows" :key="r.index" class="receipt-row" :class="{ skipped: r.choice === 'skip' }">
            <div class="row between small" style="flex-wrap: nowrap; align-items: flex-start">
              <span style="min-width: 0; overflow-wrap: anywhere">{{ r.item.name }}</span>
              <span class="nowrap num muted">{{ fmt(r.item.quantity, n(r.item.quantity) % 1 ? 3 : 0) }} × {{ fmt(r.item.price, 2) }} = <b>{{ fmt(r.item.sum, 2) }} ₽</b></span>
            </div>
            <div class="row" style="flex-wrap: nowrap">
              <select v-model="r.choice" class="grow" style="min-width: 0">
                <option value="skip">— не учитывать</option>
                <optgroup v-if="lines.length" label="Из списка покупок">
                  <option v-for="l in lines" :key="l.id" :value="'line:' + l.id"
                          :disabled="usedLines.has('line:' + l.id) && r.choice !== 'line:' + l.id">{{ l.product_name }}</option>
                </optgroup>
                <option value="product">Продукт не из списка…</option>
              </select>
              <template v-if="r.choice !== 'skip'">
                <input type="number" min="0.1" step="any" v-model="r.quantity" @input="r.qtyEdited = true" style="width: 84px" placeholder="авто" aria-label="Количество">
                <span class="small muted">{{ UNIT_LABEL[unitOf(r)] }}</span>
              </template>
            </div>
            <Picker v-if="r.choice === 'product'" :items="productItems" v-model="r.product_id" placeholder="Какой продукт…" />
            <span v-if="r.choice !== 'skip' && SOURCE[r.source]" class="tiny muted">{{ SOURCE[r.source] }}{{ r.source !== 'alias' ? ' · ' + Math.round(r.confidence * 100) + '%' : '' }}</span>
          </div>
        </div>
      </template>

      <div v-if="error" class="alert error">{{ error }}</div>
      <BarcodeScanner v-if="scanning" qr @close="scanning = false" @code="submit" />
      <template #foot>
        <button v-if="receipt" @click="back">← Другой чек</button>
        <span class="grow"></span>
        <button @click="$emit('close')">{{ receipt && receipt.status === 'done' ? 'Отмена' : 'Закрыть' }}</button>
        <button v-if="receipt && receipt.status === 'done'" class="primary" :disabled="busy" @click="apply">
          Сохранить {{ chosen.length }} покуп. · {{ fmt(chosenSum, 2) }} ₽</button>
      </template>
    </Modal>`,
};
