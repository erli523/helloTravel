<template>
  <main class="home-page">
    <section class="hero-panel">
      <div>
        <p class="eyebrow">✈ AI 智能旅行规划</p>
        <h1>你的专属<br/>旅行助手</h1>
        <p class="subtitle">
          输入目的地，AI 帮你规划景点、住宿、天气、预算，
          生成完整的图文行程方案。
        </p>
        <div class="route-visual" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </div>

        <div class="features">
          <div class="feat">
            <span class="feat-icon">🏛</span>
            <div class="feat-text">
              <strong>智能景点推荐</strong>
              <span>结合高德地图真实数据，按偏好筛选最优景点</span>
            </div>
          </div>
          <div class="feat">
            <span class="feat-icon">🗓️</span>
            <div class="feat-text">
              <strong>精准时间规划</strong>
              <span>为每个景点分配合理时间段，告别行程空白</span>
            </div>
          </div>
          <div class="feat">
            <span class="feat-icon">💰</span>
            <div class="feat-text">
              <strong>全面费用预算</strong>
              <span>景点、住宿、餐饮、交通一键汇总</span>
            </div>
          </div>
        </div>
      </div>

      <form class="planner-form" @submit.prevent="handleSubmit">
        <div class="form-heading">
          <strong>规划信息</strong>
          <span>{{ formData.start_date }} · {{ formData.end_date }}</span>
        </div>
        <label>
          <span>目的地城市</span>
          <input v-model.trim="formData.city" required placeholder="例：北京、大理、成都" />
        </label>

        <div class="grid-2">
          <label>
            <span>出发日期</span>
            <input v-model="formData.start_date" required type="date" />
          </label>
          <label>
            <span>返回日期</span>
            <input v-model="formData.end_date" required type="date" />
          </label>
        </div>

        <div class="grid-2">
          <label>
            <span>出行人数</span>
            <input v-model.number="formData.travelers" min="1" max="20" type="number" />
          </label>
          <label>
            <span>预算档次</span>
            <select v-model="formData.budget_level">
              <option value="economy">经济型</option>
              <option value="comfort">舒适型</option>
              <option value="premium">高端型</option>
            </select>
          </label>
        </div>

        <div class="grid-2">
          <label>
            <span>出行方式</span>
            <select v-model="formData.transportation">
              <option value="public transit + walking">🚇 公共交通 + 步行</option>
              <option value="taxi + walking">🚖 打车 + 步行</option>
              <option value="self-driving">🚗 自驾</option>
            </select>
          </label>
          <label>
            <span>住宿偏好</span>
            <select v-model="formData.accommodation">
              <option value="economy">经济酒店</option>
              <option value="comfort">舒适酒店</option>
              <option value="premium">高档酒店</option>
            </select>
          </label>
        </div>

        <label>
          <span>总预算（元，可选）</span>
          <input v-model.number="formData.budget" min="0" placeholder="不填则不限制预算" type="number" />
        </label>

        <fieldset>
          <legend>旅行偏好</legend>
          <label v-for="item in preferenceOptions" :key="item" class="check-item">
            <input v-model="formData.preferences" :value="item" type="checkbox" />
            <span>{{ prefLabel(item) }}</span>
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
          {{ loading ? "AI 规划中…" : "✦ 开始规划" }}
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

const prefLabelMap: Record<string, string> = {
  culture: "🏛 文化历史",
  nature: "🌿 自然风光",
  food: "🍜 美食探索",
  family: "👨‍👩‍👧 亲子出行",
  "slow travel": "☕ 慢旅行",
};

function prefLabel(v: string): string {
  return prefLabelMap[v] ?? v;
}

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
    errorMessage.value = "返回日期不能早于出发日期。";
    return;
  }

  loading.value = true;
  loadingProgress.value = 0;
  loadingStatus.value = "Searching attractions...";
  errorMessage.value = "";

  const progressInterval = window.setInterval(() => {
    if (loadingProgress.value >= 90) return;
    loadingProgress.value += 10;
    if (loadingProgress.value <= 30) loadingStatus.value = "🏛 搜索景点候选…";
    else if (loadingProgress.value <= 50) loadingStatus.value = "🌤 查询天气预报…";
    else if (loadingProgress.value <= 70) loadingStatus.value = "🏨 筛选酒店方案…";
    else loadingStatus.value = "🧠 AI 智能生成行程…";
  }, 500);

  try {
    const tripPlan = await generateTripPlan({
      ...formData,
      preferences: [...formData.preferences]
    });
    window.clearInterval(progressInterval);
    loadingProgress.value = 100;
    loadingStatus.value = "✓ 规划完成";
    sessionStorage.setItem("tripPlan", JSON.stringify(tripPlan));
    await router.push({ name: "result" });
  } catch (error) {
    window.clearInterval(progressInterval);
    errorMessage.value =
      error instanceof Error ? error.message : "行程生成失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
/* ── Page shell ── */
.home-page {
  background: linear-gradient(160deg, #e6f7f4 0%, #f8fafc 50%, #fdf8f0 100%);
  color: #0f172a;
  min-height: 100vh;
  overflow-x: hidden;
  padding: 48px 24px 60px;
}

.hero-panel {
  align-items: start;
  display: grid;
  gap: 40px;
  grid-template-columns: minmax(280px, 0.85fr) minmax(380px, 1fr);
  margin: 0 auto;
  max-width: 1180px;
}

/* ── Left copy ── */
.eyebrow {
  color: #0f766e;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .07em;
  margin: 0 0 16px;
  text-transform: uppercase;
}

h1 {
  font-size: 58px;
  font-weight: 800;
  letter-spacing: -.03em;
  line-height: 1.05;
  margin: 0 0 20px;
}

.subtitle {
  color: #475569;
  font-size: 18px;
  line-height: 1.6;
  max-width: 480px;
  margin: 0 0 40px;
}

.route-visual {
  background: linear-gradient(90deg,
    #0f766e 0 30%, rgba(15,118,110,.2) 30% 36%,
    #1d4ed8 36% 65%, rgba(29,78,216,.2) 65% 71%,
    #d97706 71% 100%);
  border-radius: 6px;
  display: grid;
  gap: 18px;
  grid-template-columns: repeat(3, 1fr);
  height: 6px;
  max-width: 400px;
  position: relative;
}

.route-visual span {
  background: #fff;
  border: 3px solid #0f766e;
  border-radius: 50%;
  box-shadow: 0 4px 12px rgba(15,23,42,.16);
  height: 20px;
  justify-self: center;
  margin-top: -7px;
  width: 20px;
}

.route-visual span:nth-child(2) { border-color: #1d4ed8; }
.route-visual span:nth-child(3) { border-color: #d97706; }

/* ── Features list ── */
.features {
  display: grid;
  gap: 12px;
  margin-top: 36px;
}

.feat {
  align-items: flex-start;
  display: flex;
  gap: 12px;
}

.feat-icon {
  background: #f0fdfa;
  border: 1px solid #99f6e4;
  border-radius: 10px;
  flex-shrink: 0;
  font-size: 20px;
  padding: 8px;
}

.feat-text strong {
  display: block;
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 2px;
}

.feat-text span {
  color: #64748b;
  font-size: 13px;
}

/* ── Form card ── */
.planner-form {
  background: #fff;
  border: 1px solid rgba(15,23,42,.08);
  border-radius: 16px;
  box-shadow:
    0 4px 24px rgba(15,23,42,.07),
    0 1px 4px rgba(15,23,42,.04);
  display: grid;
  gap: 18px;
  min-width: 0;
  padding: 28px;
}

.form-heading {
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  padding-bottom: 16px;
}

.form-heading strong { font-size: 18px; font-weight: 700; }
.form-heading span   { color: #94a3b8; font-size: 13px; }

.grid-2 {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

label { display: grid; gap: 6px; }

label > span,
legend {
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

input,
select {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font: inherit;
  min-height: 42px;
  padding: 0 12px;
  transition: border-color .18s, box-shadow .18s;
  width: 100%;
}

input:focus,
select:focus {
  background: #fff;
  border-color: #0f766e;
  box-shadow: 0 0 0 3px rgba(15,118,110,.12);
  outline: none;
}

fieldset {
  border: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
}

legend { flex: 0 0 100%; margin-bottom: 4px; }

.check-item {
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  cursor: pointer;
  display: inline-flex;
  font-size: 13px;
  gap: 6px;
  min-height: 34px;
  padding: 0 12px;
  transition: background .18s, border-color .18s, color .18s;
}

.check-item input { min-height: auto; width: auto; }

.check-item:has(input:checked) {
  background: #f0fdfa;
  border-color: #0f766e;
  color: #0f766e;
  font-weight: 600;
}

/* ── Progress ── */
.progress-block { display: grid; gap: 8px; }

.progress-track {
  background: #e2e8f0;
  border-radius: 999px;
  height: 8px;
  overflow: hidden;
}

.progress-bar {
  background: linear-gradient(90deg, #0f766e, #0d9488);
  height: 100%;
  transition: width .3s ease;
}

.progress-block p,
.error-message { margin: 0; font-size: 13px; }

.progress-block p { color: #64748b; }
.error-message    { color: #dc2626; }

/* ── Submit button ── */
button[type="submit"] {
  background: linear-gradient(135deg, #0f766e, #0d9488);
  border: 0;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(15,118,110,.28);
  color: #fff;
  cursor: pointer;
  font: 700 16px/1 inherit;
  letter-spacing: .02em;
  min-height: 50px;
  transition: opacity .18s, transform .18s, box-shadow .18s;
}

button[type="submit"]:hover:not(:disabled) {
  box-shadow: 0 6px 22px rgba(15,118,110,.35);
  transform: translateY(-2px);
}

button[type="submit"]:disabled {
  cursor: wait;
  opacity: 0.65;
}

/* ── Responsive ── */
@media (max-width: 860px) {
  .home-page { padding: 20px 14px 40px; }

  .hero-panel,
  .grid-2 { grid-template-columns: 1fr; }

  h1 { font-size: 36px; }
  .features { display: none; }

  .form-heading { align-items: start; display: grid; }
}
</style>
