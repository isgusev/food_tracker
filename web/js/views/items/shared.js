// Общее для экрана «items»: константы и помощники компонентов.
import { ref, computed, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { Modal } from "../../components.js";
import { loadProducts, toast, toastError } from "../../store.js";
import { fmtQty, fuzzyScore, local } from "../../util.js";

export const HIDDEN_KEY = "ft.itemSuggestionsHidden";

export const groupId = (g) => g.items.map((i) => i.key).sort().join("|");
