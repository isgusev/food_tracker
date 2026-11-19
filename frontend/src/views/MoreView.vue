<script setup lang="ts">
// «Ещё» на телефоне: разделы, которым не хватило места в нижней панели.
import NavIcon from "../components/NavIcon.vue";
import { MORE } from "../nav";
import { session } from "../session";
</script>

<template>
  <div class="more">
    <h1 class="display">Ещё</h1>
    <nav class="list" aria-label="Другие разделы">
      <template v-for="m in MORE" :key="m.to">
        <RouterLink v-if="'next' in m" :to="m.to" class="item"><NavIcon :name="m.icon" /><span class="grow">{{ m.label }}</span><span class="muted">›</span></RouterLink>
        <a v-else :href="m.to" class="item"><NavIcon :name="m.icon" /><span class="grow">{{ m.label }}</span><span class="tiny muted">старый вид ›</span></a>
      </template>
    </nav>
    <p class="small muted">{{ session.user?.username }}<template v-if="session.household"> · {{ session.household.name }}</template></p>
  </div>
</template>

<style scoped>
.more { display: flex; flex-direction: column; gap: 14px; max-width: 560px; }
h1 { font-size: 32px; color: var(--rim); }
p { margin: 0; }
.list { display: flex; flex-direction: column; border-radius: var(--r-pot); background: var(--enamel); border: 1.5px solid var(--line); overflow: hidden; }
.item { display: flex; align-items: center; gap: 14px; min-height: 56px; padding: 0 16px; color: var(--ink); text-decoration: none; border-top: 1px solid var(--line); }
.item:first-child { border-top: 0; }
.item:hover { background: var(--rim-soft); }
.item :deep(svg) { color: var(--rim); }
.grow { flex: 1; font-weight: 600; }
</style>
