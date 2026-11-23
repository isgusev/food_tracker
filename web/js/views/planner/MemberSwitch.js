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

// Переключатель «чьи КБЖУ показываем»
export const MemberSwitch = {
  setup() {
    return { state, members: activeMembers, setViewMember };
  },
  template: `
    <div class="segmented" style="flex-wrap: wrap" v-if="members.length > 1" title="Чьи КБЖУ показывать">
      <button v-for="m in members" :key="m.id" :class="{ on: state.viewMemberId === m.id }" @click="setViewMember(m.id)">{{ m.name }}</button>
    </div>`,
};
