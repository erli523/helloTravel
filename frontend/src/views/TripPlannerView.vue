<template>
  <main class="trip-planner-view">
    <aside class="planner-panel">
      <h1>智能旅行助手</h1>
      <TripPlannerForm :loading="loading" @submit="handleSubmit" />
      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
    </aside>

    <section class="result-layout">
      <ResultPanel :plan="plan" />
      <MapPreview :plan="plan" />
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from "vue";

import MapPreview from "../components/MapPreview.vue";
import ResultPanel from "../components/ResultPanel.vue";
import TripPlannerForm from "../components/TripPlannerForm.vue";
import { createTravelPlan } from "../services/api";
import type { TravelPlanRequest, TripPlan } from "../types/travel";

const loading = ref(false);
const errorMessage = ref("");
const plan = ref<TripPlan | null>(null);

async function handleSubmit(request: TravelPlanRequest) {
  loading.value = true;
  errorMessage.value = "";

  try {
    const response = await createTravelPlan(request);
    plan.value = response.plan;
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "行程规划请求失败";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.trip-planner-view {
  background: #eef6f4;
  color: #0f172a;
  display: grid;
  gap: 24px;
  grid-template-columns: minmax(280px, 360px) 1fr;
  min-height: 100vh;
  padding: 24px;
}

.planner-panel,
.result-layout {
  background: #ffffff;
  border: 1px solid #dbe7e4;
  border-radius: 8px;
  padding: 22px;
}

.planner-panel {
  align-self: start;
  display: grid;
  gap: 18px;
  position: sticky;
  top: 24px;
}

h1 {
  font-size: 28px;
  margin: 0;
}

.result-layout {
  display: grid;
  gap: 22px;
}

.error-message {
  color: #b91c1c;
  margin: 0;
}

@media (max-width: 960px) {
  .trip-planner-view {
    grid-template-columns: 1fr;
  }

  .planner-panel {
    position: static;
  }
}

@media (max-width: 640px) {
  .trip-planner-view {
    padding: 12px;
  }
}
</style>
