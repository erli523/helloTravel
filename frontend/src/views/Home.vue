<template>
  <main class="home-page">
    <section class="hero-panel">
      <div>
        <p class="eyebrow">AI travel planning</p>
        <h1>Smart Travel Assistant</h1>
        <p class="subtitle">
          Build a day-by-day itinerary with attractions, hotels, weather,
          budget, and images.
        </p>
      </div>

      <form class="planner-form" @submit.prevent="handleSubmit">
        <label>
          <span>Destination city</span>
          <input v-model.trim="formData.city" required placeholder="Beijing" />
        </label>

        <div class="grid-2">
          <label>
            <span>Start date</span>
            <input v-model="formData.start_date" required type="date" />
          </label>
          <label>
            <span>End date</span>
            <input v-model="formData.end_date" required type="date" />
          </label>
        </div>

        <div class="grid-2">
          <label>
            <span>Travelers</span>
            <input v-model.number="formData.travelers" min="1" max="20" type="number" />
          </label>
          <label>
            <span>Budget level</span>
            <select v-model="formData.budget_level">
              <option value="economy">Economy</option>
              <option value="comfort">Comfort</option>
              <option value="premium">Premium</option>
            </select>
          </label>
        </div>

        <div class="grid-2">
          <label>
            <span>Transportation</span>
            <select v-model="formData.transportation">
              <option value="public transit + walking">Public transit + walking</option>
              <option value="taxi + walking">Taxi + walking</option>
              <option value="self-driving">Self-driving</option>
            </select>
          </label>
          <label>
            <span>Accommodation</span>
            <select v-model="formData.accommodation">
              <option value="economy">Economy hotel</option>
              <option value="comfort">Comfort hotel</option>
              <option value="premium">Premium hotel</option>
            </select>
          </label>
        </div>

        <label>
          <span>Total budget</span>
          <input v-model.number="formData.budget" min="0" placeholder="Optional" type="number" />
        </label>

        <fieldset>
          <legend>Preferences</legend>
          <label v-for="item in preferenceOptions" :key="item" class="check-item">
            <input v-model="formData.preferences" :value="item" type="checkbox" />
            <span>{{ item }}</span>
          </label>
        </fieldset>

        <div v-if="loading" class="progress-block">
          <div class="progress-track">
            <div class="progress-bar" :style="{ width: `${loadingProgress}%` }"></div>
          </div>
          <p>{{ loadingStatus }}</p>
        </div>

        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

        <button :disabled="loading" type="submit">
          {{ loading ? "Planning..." : "Start planning" }}
        </button>
      </form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { generateTripPlan } from "../services/api";
import type { TravelPlanRequest } from "../types";

const router = useRouter();

const today = new Date();
const end = new Date(today);
end.setDate(today.getDate() + 2);

const formatDate = (value: Date) => value.toISOString().slice(0, 10);
const preferenceOptions = ["culture", "nature", "food", "family", "slow travel"];

const loading = ref(false);
const loadingProgress = ref(0);
const loadingStatus = ref("");
const errorMessage = ref("");

const formData = reactive<TravelPlanRequest>({
  city: "Beijing",
  start_date: formatDate(today),
  end_date: formatDate(end),
  travelers: 2,
  budget_level: "comfort",
  budget: null,
  preferences: ["culture", "food"],
  transportation: "public transit + walking",
  accommodation: "comfort"
});

async function handleSubmit() {
  if (formData.end_date < formData.start_date) {
    errorMessage.value = "End date cannot be earlier than start date.";
    return;
  }

  loading.value = true;
  loadingProgress.value = 0;
  loadingStatus.value = "Searching attractions...";
  errorMessage.value = "";

  const progressInterval = window.setInterval(() => {
    if (loadingProgress.value >= 90) return;
    loadingProgress.value += 10;
    if (loadingProgress.value <= 30) loadingStatus.value = "Searching attractions...";
    else if (loadingProgress.value <= 50) loadingStatus.value = "Querying weather...";
    else if (loadingProgress.value <= 70) loadingStatus.value = "Recommending hotels...";
    else loadingStatus.value = "Generating itinerary...";
  }, 500);

  try {
    const tripPlan = await generateTripPlan({
      ...formData,
      preferences: [...formData.preferences]
    });
    window.clearInterval(progressInterval);
    loadingProgress.value = 100;
    loadingStatus.value = "Done";
    sessionStorage.setItem("tripPlan", JSON.stringify(tripPlan));
    await router.push({ name: "result" });
  } catch (error) {
    window.clearInterval(progressInterval);
    errorMessage.value =
      error instanceof Error ? error.message : "Failed to generate trip plan.";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.home-page {
  background: #eef6f4;
  color: #0f172a;
  min-height: 100vh;
  padding: 32px;
}

.hero-panel {
  display: grid;
  gap: 28px;
  grid-template-columns: minmax(260px, 0.85fr) minmax(320px, 1fr);
  margin: 0 auto;
  max-width: 1120px;
}

.eyebrow {
  color: #0f766e;
  font-weight: 700;
  margin: 0 0 8px;
}

h1 {
  font-size: 44px;
  line-height: 1.05;
  margin: 0;
}

.subtitle {
  color: #475569;
  font-size: 18px;
  max-width: 520px;
}

.planner-form {
  background: #ffffff;
  border: 1px solid #dbe7e4;
  border-radius: 8px;
  display: grid;
  gap: 16px;
  padding: 22px;
}

.grid-2 {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

label {
  display: grid;
  gap: 7px;
}

label span,
legend {
  color: #334155;
  font-size: 14px;
  font-weight: 700;
}

input,
select {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font: inherit;
  min-height: 42px;
  padding: 0 12px;
}

fieldset {
  border: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
}

legend {
  flex: 0 0 100%;
  margin-bottom: 4px;
}

.check-item {
  align-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  display: inline-flex;
  gap: 6px;
  min-height: 36px;
  padding: 0 10px;
}

.check-item input {
  min-height: auto;
}

.progress-block {
  display: grid;
  gap: 8px;
}

.progress-track {
  background: #e2e8f0;
  border-radius: 999px;
  height: 10px;
  overflow: hidden;
}

.progress-bar {
  background: #0f766e;
  height: 100%;
  transition: width 0.25s ease;
}

.progress-block p,
.error-message {
  margin: 0;
}

.error-message {
  color: #b91c1c;
}

button {
  background: #0f766e;
  border: 0;
  border-radius: 8px;
  color: white;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  min-height: 46px;
}

button:disabled {
  cursor: wait;
  opacity: 0.7;
}

@media (max-width: 860px) {
  .home-page {
    padding: 14px;
  }

  .hero-panel,
  .grid-2 {
    grid-template-columns: 1fr;
  }

  h1 {
    font-size: 34px;
  }
}
</style>
