<template>
  <section class="result-panel">
    <div v-if="!plan" class="empty-state">
      <h2>行程结果</h2>
      <p>填写左侧表单后，这里会展示每日行程、天气和预算。</p>
    </div>

    <template v-else>
      <header class="result-header">
        <div>
          <p>{{ plan.start_date }} 至 {{ plan.end_date }}</p>
          <h2>{{ plan.city }}旅行计划</h2>
        </div>
        <strong v-if="plan.budget">¥{{ plan.budget.total }}</strong>
      </header>

      <div class="summary-grid">
        <div v-if="plan.budget" class="summary-item">
          <span>门票</span>
          <strong>¥{{ plan.budget.total_attractions }}</strong>
        </div>
        <div v-if="plan.budget" class="summary-item">
          <span>住宿</span>
          <strong>¥{{ plan.budget.total_hotels }}</strong>
        </div>
        <div v-if="plan.budget" class="summary-item">
          <span>餐饮</span>
          <strong>¥{{ plan.budget.total_meals }}</strong>
        </div>
        <div v-if="plan.budget" class="summary-item">
          <span>交通</span>
          <strong>¥{{ plan.budget.total_transportation }}</strong>
        </div>
      </div>

      <p class="suggestion">{{ plan.overall_suggestions }}</p>

      <article v-for="day in plan.days" :key="day.date" class="day-card">
        <div class="day-title">
          <div>
            <span>Day {{ day.day_index + 1 }}</span>
            <h3>{{ day.date }}</h3>
          </div>
          <p>{{ weatherText(day.date) }}</p>
        </div>

        <p>{{ day.description }}</p>
        <dl>
          <div>
            <dt>交通</dt>
            <dd>{{ day.transportation }}</dd>
          </div>
          <div>
            <dt>住宿</dt>
            <dd>{{ day.hotel?.name || day.accommodation }}</dd>
          </div>
        </dl>

        <div class="attraction-list">
          <section
            v-for="attraction in day.attractions"
            :key="attraction.name"
            class="attraction-item"
          >
            <img
              v-if="attraction.image_url"
              :src="attraction.image_url"
              :alt="attraction.name"
            />
            <div>
              <h4>{{ attraction.name }}</h4>
              <p>{{ attraction.description }}</p>
              <span>{{ attraction.category }} · {{ attraction.visit_duration }}分钟 · ¥{{ attraction.ticket_price }}</span>
            </div>
          </section>
        </div>
      </article>
    </template>
  </section>
</template>

<script setup lang="ts">
import type { TripPlan } from "../types/travel";

const props = defineProps<{
  plan: TripPlan | null;
}>();

function weatherText(date: string) {
  const weather = props.plan?.weather_info.find((item) => item.date === date);
  if (!weather) {
    return "暂无天气";
  }
  return `${weather.day_weather} ${weather.day_temp}°C / ${weather.night_temp}°C`;
}
</script>

<style scoped>
.result-panel {
  display: grid;
  gap: 18px;
}

.empty-state {
  border: 1px dashed #94a3b8;
  border-radius: 8px;
  min-height: 260px;
  padding: 28px;
}

.empty-state h2,
.result-header h2,
.day-title h3,
.attraction-item h4 {
  margin: 0;
}

.empty-state p,
.result-header p,
.day-card p,
dd {
  color: #475569;
}

.result-header {
  align-items: end;
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.result-header strong {
  color: #0f766e;
  font-size: 30px;
}

.summary-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.summary-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: grid;
  gap: 4px;
  padding: 12px;
}

.summary-item span,
.day-title span {
  color: #64748b;
  font-size: 13px;
}

.suggestion,
.day-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
}

.day-title {
  align-items: start;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

dl {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 14px 0;
}

dt {
  color: #64748b;
  font-size: 13px;
}

dd {
  margin: 4px 0 0;
}

.attraction-list {
  display: grid;
  gap: 12px;
}

.attraction-item {
  align-items: center;
  display: grid;
  gap: 12px;
  grid-template-columns: 96px 1fr;
}

.attraction-item img {
  aspect-ratio: 4 / 3;
  border-radius: 8px;
  object-fit: cover;
  width: 96px;
}

.attraction-item p {
  margin: 6px 0;
}

.attraction-item span {
  color: #0f766e;
  font-size: 13px;
}

@media (max-width: 720px) {
  .summary-grid,
  dl {
    grid-template-columns: 1fr;
  }

  .result-header,
  .day-title {
    display: grid;
  }
}
</style>
