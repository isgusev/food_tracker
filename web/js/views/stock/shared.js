// Общее для экрана «stock»: константы и помощники компонентов.
import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, BarcodeScanner } from "../../components.js";
import { state, ensureCatalog, toast, toastError } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, matches, n, today, UNIT_LABEL } from "../../util.js";
import { PacksEditor, packsBody, defaultPackAmount, productById } from "../../marking.js";

export const REASON = { purchase: "покупка", manual: "добавлено", inventory: "инвентаризация", cook: "готовка", eat: "съедено", write_off: "списано" };
