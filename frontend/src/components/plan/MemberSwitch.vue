<script setup lang="ts">
// Чьи КБЖУ показываем: фишки активных членов семьи (если их больше одного); выбор общий для экранов.
import { activeMembers, session, setViewMember } from "../../session";
</script>

<template>
  <div v-if="activeMembers.length > 1" class="who" role="group" aria-label="Чьи КБЖУ показывать">
    <button v-for="m in activeMembers" :key="m.id" class="chip" :class="{ on: m.id === session.viewMemberId }"
            :aria-pressed="m.id === session.viewMemberId" @click="setViewMember(m.id)">{{ m.is_me ? "Я" : m.name }}</button>
  </div>
</template>

<style scoped>
.who { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { min-height: 40px; padding: 0 14px; border-color: var(--line); color: var(--ink); font-weight: 500; }
.chip.on { background: var(--rim); border-color: var(--rim); color: var(--on-fill); font-weight: 700; }
</style>
