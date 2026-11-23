<script setup lang="ts">
// Приём пищи на «Сегодня»: блюда выбранного члена семьи, «Съел» одним касанием плановой порцией.
import { computed } from "vue";
import type { Schemas } from "../api/client";
import { fmt, grams, num } from "../util";

type Item = Schemas["MealItemResponse"];
type Portion = Schemas["PortionResponse"];

const props = defineProps<{ label: string; items: Item[]; memberId: number | null; now: boolean; busy: boolean }>();
const emit = defineEmits<{ eat: [portion: Portion]; uneat: [portion: Portion]; accept: [item: Item] }>();

const rows = computed(() => props.items.map((it) => ({ it, p: it.portions.find((x) => x.member_id === props.memberId) ?? null })));
const mine = computed(() => rows.value.filter((r) => r.p));
const done = computed(() => mine.value.length > 0 && mine.value.every((r) => r.p!.is_eaten));
const kcal = computed(() => mine.value.reduce((s, r) => s + num(r.p!.calories), 0));

function hint(it: Item): string {
  if (it.kind === "product") return "готовый продукт";
  if (it.state === "in_fridge") return "в холодильнике";
  return "надо приготовить";
}
</script>

<template>
  <section class="pot meal" :class="{ now, done }">
    <header>
      <h2>{{ label }}</h2>
      <span v-if="now && !done" class="now-mark">сейчас</span>
      <span v-else-if="done" class="small muted">съедено</span>
      <span class="kcal small muted">{{ mine.length ? fmt(kcal) + " ккал" : "" }}</span>
    </header>
    <p v-if="!items.length" class="empty small muted">Ничего не запланировано</p>
    <ul v-else>
      <li v-for="{ it, p } in rows" :key="it.id" :class="{ draft: it.origin === 'auto', eaten: p?.is_eaten, absent: !p }">
        <div class="what">
          <div class="name">{{ it.name }}</div>
          <div class="meta small">
            <template v-if="p">{{ grams(p.weight_g) }} · {{ fmt(p.calories) }} ккал · </template>
            <template v-else>без этого едока · </template>
            <span :class="'st st-' + (it.kind === 'product' ? 'product' : it.state)">{{ hint(it) }}</span>
          </div>
          <div v-if="it.origin === 'auto' && it.auto_reason" class="reason small">{{ it.auto_reason }}</div>
        </div>
        <div class="acts">
          <button v-if="it.origin === 'auto'" class="text small" :disabled="busy" @click="emit('accept', it)">Принять</button>
          <template v-if="p">
            <button v-if="!p.is_eaten" :class="now ? 'beak' : ''" :disabled="busy" @click="emit('eat', p)"
                    :aria-label="'Съел: ' + it.name">Съел</button>
            <button v-else class="text eaten-btn" :disabled="busy" @click="emit('uneat', p)"
                    :aria-label="'Отменить «съел»: ' + it.name" title="Отменить">✓ съел</button>
          </template>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
/* ободок — только у текущего приёма пищи, остальные — тонкой линией: акцент в одном месте */
.meal { padding: 14px 16px 10px; border: 1.5px solid var(--line); }
.meal.now { border: 2px solid var(--rim); }
.meal.done { border-color: var(--line); }
header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
h2 { font-size: 18px; }
.now-mark { font-size: 12px; font-weight: 700; color: var(--beak); background: var(--beak-soft); padding: 2px 10px; border-radius: 999px; }
.kcal { margin-left: auto; }
.empty { margin: 4px 0 8px; }
ul { list-style: none; margin: 0; padding: 0; }
li { display: flex; gap: 12px; align-items: center; padding: 10px 0; border-top: 1px solid var(--line); }
li:first-child { border-top: 0; }
.what { flex: 1; min-width: 0; }
.name { font-weight: 600; word-break: break-word; }
.meta { color: var(--muted); }
.st-to_cook { color: var(--cook); }
.st-in_fridge { color: var(--rim); }
.st-product { color: var(--sky); }
.reason { font-style: italic; color: var(--graphite); }
.acts { display: flex; align-items: center; gap: 4px; flex: none; }
/* карандаш: предложение автоплана */
li.draft .name { color: var(--graphite); }
li.draft { background: repeating-linear-gradient(-45deg, transparent 0 6px, var(--graphite-soft) 6px 7px); }
li.eaten .name { color: var(--muted); }
li.absent { opacity: 0.6; }
.eaten-btn { color: var(--rim); }
/* «Съел»: строка наполняется — единственное движение экрана */
li.eaten { background: linear-gradient(90deg, var(--rim-soft) 0 100%) no-repeat left / 100% 100%; animation: fill 250ms ease-out; border-radius: var(--r-in); padding-left: 8px; padding-right: 8px; }
@keyframes fill { from { background-size: 0% 100%; } to { background-size: 100% 100%; } }
</style>
