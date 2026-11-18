// Общее для экрана «shopping»: константы и помощники компонентов.
import { ref, computed, watch, onMounted, onBeforeUnmount } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal } from "../../components.js";
import { ReceiptModal } from "../../receipts.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../../product-finder.js";
import { state, ensureCatalog, variantIndex, toast, toastError } from "../../store.js";
import { addDays, fmt, fmtDayMonth, fmtQty, local, n, startOfWeek, today, UNIT_LABEL } from "../../util.js";

export const POLL_MS = 15000;

export function pkgText(l) {
  if (l.package_amount && l.package_count) {
    const one = fmtQty(l.package_amount, l.unit);
    return l.package_count === 1 && l.unit === "pcs" && n(l.package_amount) === 1 ? fmtQty(l.package_count, "pcs") : `${l.package_count} × ${one}`;
  }
  return l.needed ? fmtQty(l.needed, l.unit) : "";
}
