<template>
  <form class="trip-planner-form" @submit.prevent="submitForm">
    <div class="field">
      <label for="city">Destination</label>
      <input id="city" v-model.trim="form.city" type="text" required />
    </div>

    <div class="field-grid">
      <div class="field">
        <label for="start-date">Start date</label>
        <input id="start-date" v-model="form.start_date" type="date" required />
      </div>
      <div class="field">
        <label for="end-date">End date</label>
        <input id="end-date" v-model="form.end_date" type="date" required />
      </div>
    </div>

    <div class="field-grid">
      <div class="field">
        <label for="travelers">Travelers</label>
        <input
          id="travelers"
          v-model.number="form.travelers"
          min="1"
          max="20"
          type="number"
        />
      </div>
      <div class="field">
        <label for="budget-level">Budget level</label>
        <select id="budget-level" v-model="form.budget_level">
          <option value="economy">Economy</option>
          <option value="comfort">Comfort</option>
          <option value="premium">Premium</option>
        </select>
      </div>
    </div>

    <div class="field-grid">
      <div class="field">
        <label for="transportation">Transportation</label>
        <select id="transportation" v-model="form.transportation">
          <option value="public transit + walking">Public transit + walking</option>
          <option value="taxi + walking">Taxi + walking</option>
          <option value="self-driving">Self-driving</option>
        </select>
      </div>
      <div class="field">
        <label for="accommodation">Accommodation</label>
        <select id="accommodation" v-model="form.accommodation">
          <option value="economy">Economy hotel</option>
          <option value="comfort">Comfort hotel</option>
          <option value="premium">Premium hotel</option>
        </select>
      </div>
    </div>

    <div class="field">
      <label for="budget">Total budget</label>
      <input
        id="budget"
        v-model.number="form.budget"
        min="0"
        placeholder="Optional"
        type="number"
      />
    </div>

    <div class="preference-group" aria-label="Travel preferences">
      <label
        v-for="item in preferenceOptions"
        :key="item"
        class="preference-option"
      >
        <input v-model="form.preferences" :value="item" type="checkbox" />
        <span>{{ item }}</span>
      </label>
    </div>

    <p v-if="errorMessage" class="form-error">{{ errorMessage }}</p>

    <button :disabled="loading" type="submit">
      {{ loading ? "Planning..." : "Generate plan" }}
    </button>
  </form>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";

import type { TravelPlanRequest } from "../types/travel";

defineProps<{
  loading: boolean;
}>();

const emit = defineEmits<{
  submit: [request: TravelPlanRequest];
}>();

const today = new Date();
const tomorrow = new Date(today);
tomorrow.setDate(today.getDate() + 1);

const formatDate = (value: Date) => value.toISOString().slice(0, 10);

const preferenceOptions = ["culture", "nature", "food", "family", "slow travel"];
const errorMessage = ref("");

const form = reactive<TravelPlanRequest>({
  city: "Beijing",
  start_date: formatDate(today),
  end_date: formatDate(tomorrow),
  travelers: 2,
  budget_level: "comfort",
  budget: null,
  transportation: "public transit + walking",
  accommodation: "comfort",
  preferences: ["culture", "food"]
});

function submitForm() {
  errorMessage.value = "";

  if (form.end_date < form.start_date) {
    errorMessage.value = "End date cannot be earlier than start date.";
    return;
  }

  emit("submit", { ...form, preferences: [...form.preferences] });
}
</script>

<style scoped>
.trip-planner-form {
  display: grid;
  gap: 16px;
}

.field,
.field-grid {
  display: grid;
  gap: 8px;
}

.field-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

label {
  color: #334155;
  font-size: 14px;
  font-weight: 600;
}

input,
select {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font: inherit;
  min-height: 42px;
  padding: 0 12px;
}

.preference-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preference-option {
  align-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  display: inline-flex;
  gap: 6px;
  min-height: 36px;
  padding: 0 10px;
}

.preference-option input {
  min-height: auto;
}

.form-error {
  color: #b91c1c;
  margin: 0;
}

button {
  background: #0f766e;
  border: 0;
  border-radius: 8px;
  color: white;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  min-height: 44px;
}

button:disabled {
  cursor: wait;
  opacity: 0.7;
}

@media (max-width: 720px) {
  .field-grid {
    grid-template-columns: 1fr;
  }
}
</style>
