<template>
  <main class="result-page">
    <!-- ── Side navigation ── -->
    <aside class="side-nav">
      <RouterLink class="back-link" to="/">✦ 新建行程</RouterLink>
      <div class="nav-title">
        <span>行程导航</span>
        <strong>{{ tripPlan?.city || "旅行" }}</strong>
      </div>
      <button
        v-for="item in navItems"
        :key="item.key"
        :class="{ active: activeSection === item.key }"
        type="button"
        @click="scrollToSection(item.key)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        {{ item.label }}
      </button>
    </aside>

    <!-- ── Empty state ── -->
    <section v-if="!tripPlan" class="missing-state">
      <div class="missing-icon">🗺️</div>
      <h1>暂无行程</h1>
      <p>请先在首页生成您的专属旅行方案。</p>
      <RouterLink to="/" class="missing-link">前往规划页面</RouterLink>
    </section>

    <!-- ── Main content ── -->
    <section v-else class="result-shell">

      <!-- Hero Banner -->
      <div class="hero" :class="{ exporting: isExporting }">
        <div class="hero-content">
          <p class="hero-eyebrow">✈ AI 智能行程规划</p>
          <h1 class="hero-city">{{ tripPlan.city }}</h1>
          <p class="hero-dates">{{ tripPlan.start_date }} — {{ tripPlan.end_date }}</p>
          <div class="hero-stats">
            <span>🗓 {{ tripPlan.days.length }} 天</span>
            <span>🏛 {{ totalAttractions }} 个景点</span>
            <span v-if="tripPlan.budget">💰 ¥{{ tripPlan.budget.total }}</span>
          </div>
        </div>
        <div class="hero-actions">
          <button type="button" class="btn-outline" @click="exportAsImage">📷 导出图片</button>
          <button type="button" class="btn-outline" @click="exportAsPDF">📄 导出 PDF</button>
          <button v-if="!editMode" type="button" class="btn-ghost" @click="enterEditMode">✏️ 编辑</button>
          <button v-if="editMode" type="button" class="btn-primary" @click="saveChanges">✓ 保存</button>
          <button v-if="editMode" type="button" class="btn-ghost" @click="cancelEdit">✕ 取消</button>
        </div>
      </div>

      <div id="trip-plan-content" class="content-stack">

        <!-- 01 概览 -->
        <section id="overview" class="panel">
          <div class="section-heading">
            <span class="sh-icon">💡</span>
            <h2>行程概览</h2>
          </div>
          <div class="overview-body">
            <p
              v-for="(line, i) in (tripPlan.overall_suggestions || '').split('\n').filter(Boolean)"
              :key="i"
            >{{ line }}</p>
          </div>
        </section>

        <!-- 02 预算 -->
        <section v-if="tripPlan.budget" id="budget" class="panel">
          <div class="section-heading">
            <span class="sh-icon">💰</span>
            <h2>费用预算</h2>
            <span class="section-badge">¥{{ tripPlan.budget.total }} 合计</span>
          </div>

          <!-- 4 category cards -->
          <div class="budget-cards">
            <div class="budget-card bc-attraction">
              <span class="bc-icon">🏛</span>
              <span class="bc-label">景点门票</span>
              <strong>¥{{ tripPlan.budget.total_attractions }}</strong>
              <div class="bc-bar">
                <div
                  class="bc-fill"
                  :style="{ width: budgetPct(tripPlan.budget.total_attractions, tripPlan.budget.total) + '%' }"
                ></div>
              </div>
            </div>
            <div class="budget-card bc-hotel">
              <span class="bc-icon">🏨</span>
              <span class="bc-label">住宿费用</span>
              <strong>¥{{ tripPlan.budget.total_hotels }}</strong>
              <div class="bc-bar">
                <div
                  class="bc-fill"
                  :style="{ width: budgetPct(tripPlan.budget.total_hotels, tripPlan.budget.total) + '%' }"
                ></div>
              </div>
            </div>
            <div class="budget-card bc-meal">
              <span class="bc-icon">🍜</span>
              <span class="bc-label">餐饮费用</span>
              <strong>¥{{ tripPlan.budget.total_meals }}</strong>
              <div class="bc-bar">
                <div
                  class="bc-fill"
                  :style="{ width: budgetPct(tripPlan.budget.total_meals, tripPlan.budget.total) + '%' }"
                ></div>
              </div>
            </div>
            <div class="budget-card bc-transport">
              <span class="bc-icon">🚌</span>
              <span class="bc-label">交通费用</span>
              <strong>¥{{ tripPlan.budget.total_transportation }}</strong>
              <div class="bc-bar">
                <div
                  class="bc-fill"
                  :style="{ width: budgetPct(tripPlan.budget.total_transportation, tripPlan.budget.total) + '%' }"
                ></div>
              </div>
            </div>
          </div>

          <p class="budget-meta">
            {{ tripPlan.budget.travelers }} 人出行 · 住宿 {{ tripPlan.budget.hotel_nights }} 晚
          </p>

          <!-- Detail table -->
          <details class="budget-detail-wrap">
            <summary>查看费用明细</summary>
            <div class="budget-detail-table">
              <div class="budget-detail-head">
                <span>类别</span>
                <span>项目</span>
                <span>单价</span>
                <span>数量</span>
                <span>小计</span>
              </div>
              <div
                v-for="detail in tripPlan.budget.details"
                :key="`${detail.category}-${detail.item}`"
                class="budget-detail-row"
              >
                <span>{{ detail.category }}</span>
                <span>
                  <strong>{{ detail.item }}</strong>
                  <small>{{ detail.note }}</small>
                </span>
                <span>¥{{ detail.unit_cost }}</span>
                <span>{{ detail.quantity }}</span>
                <span class="subtotal">¥{{ detail.subtotal }}</span>
              </div>
            </div>
          </details>
        </section>

        <!-- 03 地图 -->
        <section id="map" class="panel map-panel" :class="{ exporting: isExporting }">
          <div class="section-heading">
            <span class="sh-icon">🗺️</span>
            <h2>景点地图</h2>
          </div>
          <div ref="mapContainer" class="amap-container">
            <div v-if="mapFallback" class="map-fallback">
              <span>🗺️</span>
              <p>{{ mapFallback }}</p>
            </div>
          </div>
        </section>

        <!-- 04 每日行程 -->
        <section id="days" class="panel">
          <div class="section-heading">
            <span class="sh-icon">🗓️</span>
            <h2>每日行程</h2>
          </div>

          <article
            v-for="(day, dayIndex) in tripPlan.days"
            :key="day.date"
            class="day-card"
            :data-day-idx="day.day_index % 5"
          >
            <!-- Day header -->
            <div class="day-header">
              <div class="day-badge">{{ day.day_index + 1 }}</div>
              <div class="day-info">
                <h3>{{ day.description || `第 ${day.day_index + 1} 天` }}</h3>
                <div class="day-meta-row">
                  <span class="day-date">📅 {{ day.date }}</span>
                  <span class="day-transport-tag">{{ transportLabel(day.transportation) }}</span>
                </div>
              </div>
            </div>
            <div class="hotel-chip">🏨 {{ day.hotel?.name || day.accommodation }}</div>

            <!-- Timeline cards -->
            <div v-if="day.timeline && day.timeline.length" class="day-timeline">
              <div
                v-for="(item, ti) in day.timeline"
                :key="`${day.date}-tl-${ti}`"
                :class="['tl-card', `tl-${item.item_type}`]"
              >
                <div class="tl-times">
                  <span class="tl-start">{{ item.time }}</span>
                  <span class="tl-arrow">↓</span>
                  <span class="tl-end">{{ item.end_time }}</span>
                </div>
                <div class="tl-content">
                  <div class="tl-header">
                    <span class="tl-icon">{{ timelineIcon(item.item_type) }}</span>
                    <strong class="tl-title">{{ item.activity }}</strong>
                  </div>
                  <p v-if="item.notes" class="tl-notes">{{ item.notes }}</p>
                  <small v-if="item.location" class="tl-loc">📍 {{ item.location }}</small>
                </div>
              </div>
            </div>

            <!-- Fallback meal list -->
            <div v-else class="meal-list">
              <div v-for="meal in day.meals" :key="`${day.date}-${meal.type}-${meal.name}`" class="meal-card">
                <span class="meal-type">{{ mealTypeLabel(meal.type) }}</span>
                <strong>{{ meal.name }}</strong>
                <p>{{ meal.address || meal.description }}</p>
              </div>
            </div>

            <!-- Attraction cards -->
            <div v-if="day.attractions.length" class="attractions">
              <div class="attractions-label">本日景点</div>
              <div
                v-for="(attraction, attractionIndex) in day.attractions"
                :key="`${day.date}-${attraction.name}`"
                class="attraction-card"
              >
                <div class="attraction-img-wrap">
                  <img
                    v-if="attraction.image_url"
                    :src="attraction.image_url"
                    :alt="attraction.name"
                    loading="lazy"
                    referrerpolicy="no-referrer"
                    @error="handleImageError(attraction)"
                  />
                  <div class="img-placeholder" v-else>
                    <span>🏛️</span>
                  </div>
                </div>
                <div class="attraction-body">
                  <h4>{{ attraction.name }}</h4>
                  <p class="attraction-desc">{{ cleanDescription(attraction.description) }}</p>
                  <div class="attraction-tags">
                    <span class="tag tag-cat">{{ attraction.category }}</span>
                    <span class="tag tag-time">⏱ {{ attraction.visit_duration }} 分钟</span>
                    <span class="tag tag-price">
                      {{ attraction.ticket_price > 0 ? '¥' + attraction.ticket_price : '免费' }}
                    </span>
                    <span v-if="attraction.rating" class="tag tag-rating">⭐ {{ attraction.rating }}</span>
                  </div>
                </div>
                <div v-if="editMode" class="edit-controls">
                  <button type="button" @click="moveAttraction(dayIndex, attractionIndex, 'up')">↑</button>
                  <button type="button" @click="moveAttraction(dayIndex, attractionIndex, 'down')">↓</button>
                  <button type="button" class="btn-del" @click="deleteAttraction(dayIndex, attractionIndex)">✕</button>
                </div>
              </div>
            </div>
          </article>
        </section>

        <!-- 05 天气 -->
        <section id="weather" class="panel">
          <div class="section-heading">
            <span class="sh-icon">🌤</span>
            <h2>天气预报</h2>
          </div>
          <div class="weather-grid">
            <div v-for="weather in tripPlan.weather_info" :key="weather.date" class="weather-card">
              <span class="weather-date">{{ weather.date }}</span>
              <span class="weather-icon">{{ weatherIcon(weather.day_weather) }}</span>
              <span class="weather-desc">{{ weather.day_weather }}</span>
              <span class="weather-temp">{{ weather.day_temp }}° / {{ weather.night_temp }}°</span>
              <span class="weather-wind">{{ weather.wind_direction }}风 {{ weather.wind_power }}级</span>
            </div>
          </div>
        </section>

        <!-- 06 Agent 工作流 -->
        <section id="agents" class="panel">
          <div class="section-heading">
            <span class="sh-icon">🤖</span>
            <h2>AI Agent 工作流</h2>
          </div>
          <div class="agent-grid">
            <article v-for="trace in agentTraces" :key="trace.agent_name" class="agent-card">
              <div class="agent-header">
                <span class="agent-name">{{ agentLabel(trace.agent_name) }}</span>
                <span class="agent-summary">{{ trace.summary }}</span>
              </div>
              <p class="agent-response">{{ trace.agent_response || trace.reasoning_summary }}</p>
              <details class="agent-detail">
                <summary>查看详细推理</summary>
                <div class="agent-trace-body">
                  <p><b>推理过程</b>：{{ trace.reasoning_summary }}</p>
                  <div v-if="trace.tool_calls.length">
                    <b>工具调用：</b>
                    <code v-for="call in trace.tool_calls" :key="call">{{ call }}</code>
                  </div>
                  <p v-else class="no-tools">未调用外部工具</p>
                </div>
              </details>
            </article>
          </div>
        </section>

      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import AMapLoader from "@amap/amap-jsapi-loader";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
import { computed, nextTick, onMounted, ref } from "vue";

import { getAgentTraces } from "../services/api";
import type { AgentTrace, Attraction, TripPlan } from "../types";

const navItems = [
  { key: "overview", label: "行程概览", icon: "💡" },
  { key: "budget",   label: "费用预算", icon: "💰" },
  { key: "map",      label: "景点地图", icon: "🗺️" },
  { key: "days",     label: "每日行程", icon: "🗓️" },
  { key: "weather",  label: "天气预报", icon: "🌤" },
  { key: "agents",   label: "AI 工作流", icon: "🤖" },
];

const tripPlan = ref<TripPlan | null>(loadTripPlan());
const originalPlan = ref<TripPlan | null>(null);
const editMode = ref(false);
const activeSection = ref("overview");
const mapContainer = ref<HTMLElement | null>(null);
const mapFallback = ref("");
const isExporting = ref(false);
const agentTraces = ref<AgentTrace[]>([]);
const totalAttractions = computed(() => allAttractions().length);
let mapInstance: any = null;

function loadTripPlan() {
  const raw = sessionStorage.getItem("tripPlan");
  return raw ? (JSON.parse(raw) as TripPlan) : null;
}

function persistPlan() {
  if (tripPlan.value) {
    sessionStorage.setItem("tripPlan", JSON.stringify(tripPlan.value));
  }
}

function scrollToSection(key: string) {
  activeSection.value = key;
  document.getElementById(key)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function enterEditMode() {
  if (!tripPlan.value) return;
  originalPlan.value = JSON.parse(JSON.stringify(tripPlan.value));
  editMode.value = true;
}

function saveChanges() {
  editMode.value = false;
  originalPlan.value = null;
  persistPlan();
  void nextTick(initMap);
}

function cancelEdit() {
  if (originalPlan.value) {
    tripPlan.value = originalPlan.value;
    persistPlan();
  }
  editMode.value = false;
  originalPlan.value = null;
  void nextTick(initMap);
}

function moveAttraction(dayIndex: number, attractionIndex: number, direction: "up" | "down") {
  const attractions = tripPlan.value?.days[dayIndex]?.attractions;
  if (!attractions) return;
  const newIndex = direction === "up" ? attractionIndex - 1 : attractionIndex + 1;
  if (newIndex < 0 || newIndex >= attractions.length) return;
  [attractions[attractionIndex], attractions[newIndex]] = [
    attractions[newIndex],
    attractions[attractionIndex]
  ];
}

function deleteAttraction(dayIndex: number, attractionIndex: number) {
  tripPlan.value?.days[dayIndex]?.attractions.splice(attractionIndex, 1);
}

function handleImageError(attraction: Attraction) {
  attraction.image_url = null;
}

function timelineIcon(type: string): string {
  const icons: Record<string, string> = {
    attraction: "🏛️",
    meal: "🍽️",
    transit: "🚶",
    rest: "☕",
  };
  return icons[type] ?? "📍";
}

function allAttractions(): Attraction[] {
  return tripPlan.value?.days.flatMap((day) => day.attractions) ?? [];
}

function transportLabel(v: string): string {
  const map: Record<string, string> = {
    "public transit + walking": "🚇 公共交通+步行",
    "taxi + walking": "🚖 打车+步行",
    "self-driving": "🚗 自驾",
  };
  return map[v] ?? v;
}

function mealTypeLabel(v: string): string {
  const map: Record<string, string> = { breakfast: "早餐", lunch: "午餐", dinner: "晚餐", snack: "小食" };
  return map[v] ?? v;
}

function agentLabel(name: string): string {
  const map: Record<string, string> = {
    AttractionSearchAgent: "🏛 景点搜索",
    WeatherQueryAgent: "🌤 天气查询",
    HotelAgent: "🏨 酒店推荐",
    FoodRecommendationAgent: "🍜 美食推荐",
    PlannerAgent: "🧠 行程规划",
  };
  return map[name] ?? name;
}

function weatherIcon(desc: string): string {
  if (!desc) return "🌈";
  if (desc.includes("晴")) return "☀️";
  if (desc.includes("多云")) return "⛅";
  if (desc.includes("阴")) return "☁️";
  if (desc.includes("雨")) return "🌧️";
  if (desc.includes("雪")) return "❄️";
  if (desc.includes("雾")) return "🌫️";
  return "🌈";
}

function budgetPct(part: number, total: number): number {
  if (!total) return 0;
  return Math.round((part / total) * 100);
}

function cleanDescription(desc: string): string {
  if (!desc) return "";
  // Strip internal "Matched keywords: ..." suffix
  const idx = desc.indexOf("Matched keywords:");
  return idx > 0 ? desc.slice(0, idx).trim().replace(/\.$/, "") : desc;
}

async function initMap() {
  const points = allAttractions();
  if (!mapContainer.value || points.length === 0) {
    mapFallback.value = "暂无景点坐标，无法加载地图。";
    return;
  }

  const key = import.meta.env.VITE_AMAP_WEB_KEY as string | undefined;
  if (!key) {
    mapFallback.value = "请在 .env 中配置 VITE_AMAP_WEB_KEY 以启用地图。";
    return;
  }

  try {
    const AMap = await AMapLoader.load({ key, version: "2.0" });
    const first = points[0].location;
    mapInstance?.destroy?.();
    mapInstance = new AMap.Map(mapContainer.value, {
      center: [first.longitude, first.latitude],
      zoom: 12
    });
    const markers = points.map((attraction, index) => {
      const marker = new AMap.Marker({
        position: [attraction.location.longitude, attraction.location.latitude],
        title: attraction.name,
        label: { content: `${index + 1}`, direction: "top" }
      });
      mapInstance.add(marker);
      return marker;
    });
    if (markers.length > 1) {
      mapInstance.setFitView(markers, false, [36, 36, 36, 36], 13);
    }
    mapFallback.value = "";
  } catch (error) {
    mapFallback.value = "地图加载失败，景点坐标已在行程中标注。";
    console.error(error);
  }
}

async function captureContent() {
  const element = document.getElementById("trip-plan-content");
  if (!element) return null;
  isExporting.value = true;
  await nextTick();
  const canvas = await html2canvas(element, {
    backgroundColor: "#ffffff",
    scale: 2,
    useCORS: true
  });
  isExporting.value = false;
  return canvas;
}

async function exportAsImage() {
  const canvas = await captureContent();
  if (!canvas || !tripPlan.value) return;
  const link = document.createElement("a");
  link.download = `${tripPlan.value.city}-travel-plan.png`;
  link.href = canvas.toDataURL("image/png");
  link.click();
}

async function exportAsPDF() {
  const canvas = await captureContent();
  if (!canvas || !tripPlan.value) return;
  const imgData = canvas.toDataURL("image/png");
  const pdf = new jsPDF("p", "mm", "a4");

  const pageWidth = 210;   // A4 width  in mm
  const pageHeight = 297;  // A4 height in mm
  const imgWidth = pageWidth;
  const imgHeight = (canvas.height * imgWidth) / canvas.width;

  // Split the full-height image across as many A4 pages as needed.
  // On each page the image is shifted upward so the correct slice is visible.
  let remainingHeight = imgHeight;
  let yOffset = 0;

  while (remainingHeight > 0) {
    pdf.addImage(imgData, "PNG", 0, -yOffset, imgWidth, imgHeight);
    remainingHeight -= pageHeight;
    if (remainingHeight > 0) {
      pdf.addPage();
      yOffset += pageHeight;
    }
  }

  pdf.save(`${tripPlan.value.city}-travel-plan.pdf`);
}

onMounted(() => {
  void initMap();
  void loadAgentTraces();
});

async function loadAgentTraces() {
  try {
    agentTraces.value = await getAgentTraces();
  } catch (error) {
    console.warn("Failed to load Agent traces", error);
  }
}
</script>

<style scoped>
/* ═══════════════════════════════════════
   Design tokens
═══════════════════════════════════════ */
:root {
  --c-primary: #0f766e;
  --c-primary-2: #0d9488;
  --c-primary-bg: #f0fdfa;
  --c-amber: #d97706;
  --c-amber-bg: #fffbeb;
  --c-surface: #ffffff;
  --c-surface-2: #f8fafc;
  --c-border: #e2e8f0;
  --c-text: #0f172a;
  --c-text-2: #475569;
  --c-text-3: #94a3b8;
  --shadow-sm: 0 1px 3px rgba(15,23,42,.06), 0 1px 2px rgba(15,23,42,.04);
  --shadow-md: 0 4px 16px rgba(15,23,42,.08), 0 2px 4px rgba(15,23,42,.04);
  --shadow-lg: 0 12px 40px rgba(15,23,42,.10), 0 4px 8px rgba(15,23,42,.04);
  --radius: 12px;
  --radius-sm: 8px;
}

/* ── Page shell ── */
.result-page {
  background: linear-gradient(160deg, #e6f7f4 0%, #f8fafc 50%, #fdf8f0 100%);
  color: var(--c-text);
  display: grid;
  gap: 20px;
  grid-template-columns: 220px minmax(0, 1fr);
  min-height: 100vh;
  overflow-x: hidden;
  padding: 20px;
  width: 100%;
}

/* ── Side nav ── */
.side-nav {
  align-self: start;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
  display: grid;
  gap: 4px;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  padding: 14px;
  position: sticky;
  top: 20px;
  width: 220px;
}

.nav-title {
  border-bottom: 1px solid var(--c-border);
  display: grid;
  gap: 2px;
  margin-bottom: 6px;
  padding: 4px 4px 12px;
}

.nav-title span {
  color: var(--c-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.nav-title strong {
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.back-link {
  background: var(--c-primary);
  border: none;
  border-radius: var(--radius-sm);
  color: #fff;
  cursor: pointer;
  display: block;
  font: 600 14px/1 inherit;
  padding: 11px 12px;
  text-align: center;
  text-decoration: none;
  transition: background .18s, transform .18s;
}

.back-link:hover { background: var(--c-primary-2); transform: translateY(-1px); }

.side-nav button {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--c-text-2);
  cursor: pointer;
  display: flex;
  font: 14px/1.2 inherit;
  gap: 8px;
  padding: 9px 10px;
  text-align: left;
  transition: background .15s, color .15s, border-color .15s;
}

.side-nav button:hover {
  background: var(--c-primary-bg);
  color: var(--c-primary);
}

.side-nav button.active {
  background: var(--c-primary-bg);
  border-color: #99e6de;
  color: var(--c-primary);
  font-weight: 600;
}

.nav-icon { font-size: 16px; flex-shrink: 0; }

/* ── Missing state ── */
.missing-state {
  align-items: center;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 60px 40px;
  text-align: center;
}

.missing-icon { font-size: 48px; }
.missing-state h1 { font-size: 24px; margin: 0; }
.missing-state p  { color: var(--c-text-2); margin: 0; }
.missing-link {
  background: var(--c-primary);
  border-radius: var(--radius-sm);
  color: #fff;
  padding: 10px 24px;
  text-decoration: none;
  font-weight: 600;
  transition: background .18s;
}
.missing-link:hover { background: var(--c-primary-2); }

/* ── Shell & stack ── */
.result-shell,
.content-stack {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.result-shell {
  margin: 0 auto;
  max-width: 1180px;
  width: 100%;
}

/* ── Hero Banner ── */
.hero {
  background: linear-gradient(135deg, #0f766e 0%, #0d9488 45%, #0891b2 100%);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  color: #fff;
  display: flex;
  gap: 20px;
  justify-content: space-between;
  align-items: flex-end;
  padding: 32px 28px 24px;
  position: relative;
  overflow: hidden;
}

.hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 60% 80% at 90% 10%, rgba(255,255,255,.08) 0%, transparent 60%),
    radial-gradient(ellipse 40% 60% at 10% 90%, rgba(255,255,255,.06) 0%, transparent 50%);
  pointer-events: none;
}

.hero.exporting { display: none; }

.hero-eyebrow {
  color: rgba(255,255,255,.75);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .08em;
  margin: 0 0 8px;
  text-transform: uppercase;
}

.hero-city {
  font-size: 42px;
  font-weight: 800;
  letter-spacing: -.02em;
  line-height: 1;
  margin: 0 0 8px;
  text-shadow: 0 2px 8px rgba(0,0,0,.15);
}

.hero-dates {
  color: rgba(255,255,255,.85);
  font-size: 15px;
  margin: 0 0 16px;
}

.hero-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-stats span {
  background: rgba(255,255,255,.18);
  backdrop-filter: blur(6px);
  border: 1px solid rgba(255,255,255,.25);
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  padding: 5px 12px;
}

.hero-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.btn-outline {
  background: rgba(255,255,255,.15);
  backdrop-filter: blur(6px);
  border: 1px solid rgba(255,255,255,.35);
  border-radius: var(--radius-sm);
  color: #fff;
  cursor: pointer;
  font: 600 13px/1 inherit;
  padding: 9px 14px;
  text-align: center;
  transition: background .18s, transform .18s;
  white-space: nowrap;
}

.btn-outline:hover { background: rgba(255,255,255,.25); transform: translateY(-1px); }

.btn-ghost {
  background: rgba(255,255,255,.08);
  border: 1px solid rgba(255,255,255,.22);
  border-radius: var(--radius-sm);
  color: rgba(255,255,255,.85);
  cursor: pointer;
  font: 14px/1 inherit;
  padding: 8px 14px;
  text-align: center;
  transition: background .18s;
}

.btn-ghost:hover { background: rgba(255,255,255,.18); }

.btn-primary {
  background: #fff;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--c-primary);
  cursor: pointer;
  font: 600 14px/1 inherit;
  padding: 9px 16px;
  text-align: center;
  transition: opacity .18s;
}

.btn-primary:hover { opacity: .9; }

/* ── Panels ── */
.panel {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  min-width: 0;
  padding: 24px;
}

.section-heading {
  align-items: center;
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}

.sh-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.section-heading h2 {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  flex: 1;
}

.section-badge {
  background: var(--c-primary-bg);
  border: 1px solid #99e6de;
  border-radius: 20px;
  color: var(--c-primary);
  font-size: 13px;
  font-weight: 700;
  padding: 4px 12px;
}

/* ── Overview ── */
.overview-body p {
  color: var(--c-text-2);
  line-height: 1.7;
  margin: 0 0 8px;
}

.overview-body p:last-child { margin-bottom: 0; }

/* ── Budget ── */
.budget-cards {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, 1fr);
}

.budget-card {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  display: grid;
  gap: 4px;
  padding: 14px;
}

.bc-icon { font-size: 22px; }
.bc-label { color: var(--c-text-3); font-size: 12px; font-weight: 600; }
.budget-card strong { color: var(--c-text); font-size: 20px; font-weight: 700; }

.bc-bar {
  background: var(--c-border);
  border-radius: 4px;
  height: 4px;
  margin-top: 6px;
  overflow: hidden;
}

.bc-fill {
  border-radius: 4px;
  height: 100%;
  min-width: 4px;
  transition: width .6s ease;
}

.bc-attraction { background: linear-gradient(135deg,#eff6ff,#f8fafc); }
.bc-attraction .bc-fill { background: #3b82f6; }

.bc-hotel { background: linear-gradient(135deg,#f0fdf4,#f8fafc); }
.bc-hotel .bc-fill { background: #22c55e; }

.bc-meal { background: linear-gradient(135deg,#fffbeb,#fef9f0); }
.bc-meal .bc-fill { background: #f59e0b; }

.bc-transport { background: linear-gradient(135deg,#fdf4ff,#f8fafc); }
.bc-transport .bc-fill { background: #a855f7; }

.budget-meta {
  color: var(--c-text-3);
  font-size: 13px;
  margin: 12px 0 0;
  text-align: center;
}

.budget-detail-wrap {
  margin-top: 16px;
}

.budget-detail-wrap > summary {
  color: var(--c-primary);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  padding: 6px 0;
  user-select: none;
}

.budget-detail-table {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  display: grid;
  margin-top: 10px;
  overflow-x: auto;
}

.budget-detail-head,
.budget-detail-row {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(72px, .7fr) minmax(200px, 2fr) minmax(72px, .65fr) minmax(44px, .4fr) minmax(80px, .7fr);
  min-width: 580px;
  padding: 9px 14px;
}

.budget-detail-head {
  background: var(--c-primary);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}

.budget-detail-row {
  align-items: center;
  border-top: 1px solid var(--c-border);
  font-size: 13px;
}

.budget-detail-row:nth-child(even) { background: var(--c-surface-2); }

.budget-detail-row small {
  color: var(--c-text-3);
  display: block;
  font-size: 11px;
  margin-top: 2px;
}

.subtotal { color: var(--c-primary); font-weight: 600; }

/* ── Map ── */
.amap-container {
  align-items: center;
  background:
    linear-gradient(90deg, rgba(15,118,110,.06) 1px, transparent 1px),
    linear-gradient(rgba(15,118,110,.06) 1px, transparent 1px),
    var(--c-surface-2);
  background-size: 28px 28px;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  display: flex;
  height: 360px;
  justify-content: center;
  margin-top: 4px;
  overflow: hidden;
}

.map-fallback {
  align-items: center;
  color: var(--c-text-3);
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-align: center;
}

.map-fallback span { font-size: 36px; }
.map-fallback p { font-size: 13px; margin: 0; }
.map-panel.exporting { display: none; }

/* ── Day cards ── */
.day-card {
  border-top: 2px solid var(--c-border);
  display: grid;
  gap: 14px;
  min-width: 0;
  padding: 20px 0 4px;
}

.day-card:first-child { border-top: none; }

/* Colour rotation for day badges */
.day-card[data-day-idx="0"] .day-badge { background: linear-gradient(135deg,#0f766e,#0d9488); }
.day-card[data-day-idx="1"] .day-badge { background: linear-gradient(135deg,#1d4ed8,#3b82f6); }
.day-card[data-day-idx="2"] .day-badge { background: linear-gradient(135deg,#7c3aed,#a855f7); }
.day-card[data-day-idx="3"] .day-badge { background: linear-gradient(135deg,#b45309,#d97706); }
.day-card[data-day-idx="4"] .day-badge { background: linear-gradient(135deg,#be185d,#ec4899); }

.day-header {
  align-items: flex-start;
  display: flex;
  gap: 14px;
}

.day-badge {
  align-items: center;
  border-radius: 50%;
  box-shadow: var(--shadow-md);
  color: #fff;
  display: flex;
  flex-shrink: 0;
  font-size: 20px;
  font-weight: 800;
  height: 48px;
  justify-content: center;
  width: 48px;
}

.day-info { min-width: 0; }

.day-info h3 {
  font-size: 17px;
  font-weight: 700;
  line-height: 1.3;
  margin: 0 0 6px;
  overflow-wrap: anywhere;
}

.day-meta-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.day-date {
  color: var(--c-text-3);
  font-size: 13px;
}

.day-transport-tag {
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  border-radius: 20px;
  color: var(--c-text-2);
  font-size: 12px;
  font-weight: 500;
  padding: 3px 10px;
}

.hotel-chip {
  background: var(--c-amber-bg);
  border: 1px solid #fde68a;
  border-radius: var(--radius-sm);
  color: var(--c-amber);
  font-size: 13px;
  font-weight: 500;
  padding: 5px 12px;
  width: fit-content;
}

/* ── Timeline cards ── */
.day-timeline {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tl-card {
  border-left: 3px solid var(--c-border);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  display: grid;
  gap: 10px;
  grid-template-columns: 52px 1fr;
  min-width: 0;
  padding: 10px 12px 10px 14px;
}

/* Type backgrounds & accent colours */
.tl-attraction {
  background: #eff6ff;
  border-left-color: #3b82f6;
}
.tl-meal {
  background: #f0fdf4;
  border-left-color: #22c55e;
}
.tl-transit {
  background: var(--c-surface-2);
  border-left-color: #cbd5e1;
}
.tl-rest {
  background: #fffbeb;
  border-left-color: #f59e0b;
}

.tl-times {
  align-items: center;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-top: 3px;
}

.tl-start {
  color: var(--c-text);
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
}

.tl-arrow {
  color: var(--c-text-3);
  font-size: 10px;
  line-height: 1;
}

.tl-end {
  color: var(--c-text-3);
  font-size: 11px;
  white-space: nowrap;
}

.tl-header {
  align-items: baseline;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tl-icon { font-size: 14px; flex-shrink: 0; }

.tl-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  margin: 0;
}

.tl-transit .tl-title,
.tl-transit .tl-content { opacity: .75; }

.tl-notes {
  color: var(--c-text-2);
  font-size: 12px;
  line-height: 1.55;
  margin: 4px 0 0;
}

.tl-loc {
  color: var(--c-text-3);
  display: block;
  font-size: 11px;
  margin-top: 3px;
}

/* ── Meal list fallback ── */
.meal-list {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.meal-card {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: var(--radius-sm);
  display: grid;
  gap: 4px;
  padding: 12px;
}

.meal-type {
  color: #c2410c;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
}

.meal-card strong,
.meal-card p { margin: 0; }
.meal-card p { color: #7c2d12; font-size: 12px; }

/* ── Attractions ── */
.attractions { display: grid; gap: 10px; }

.attractions-label {
  color: var(--c-text-3);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .06em;
  padding: 4px 0 2px;
  text-transform: uppercase;
}

.attraction-card {
  align-items: start;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-sm);
  display: grid;
  gap: 14px;
  grid-template-columns: 148px minmax(0, 1fr) auto;
  min-width: 0;
  padding: 12px;
  transition: box-shadow .2s, transform .2s;
}

.attraction-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.attraction-img-wrap {
  flex-shrink: 0;
  width: 148px;
}

.attraction-img-wrap img {
  aspect-ratio: 4/3;
  border-radius: var(--radius-sm);
  object-fit: cover;
  width: 100%;
}

.img-placeholder {
  align-items: center;
  aspect-ratio: 4/3;
  background: linear-gradient(135deg, rgba(15,118,110,.12), rgba(245,158,11,.1)), #dbe7e4;
  border-radius: var(--radius-sm);
  display: flex;
  font-size: 28px;
  justify-content: center;
  width: 100%;
}

.attraction-body { min-width: 0; }

.attraction-body h4 {
  font-size: 15px;
  font-weight: 700;
  margin: 0 0 6px;
  overflow-wrap: anywhere;
}

.attraction-desc {
  color: var(--c-text-2);
  font-size: 13px;
  line-height: 1.55;
  margin: 0 0 10px;
  overflow-wrap: anywhere;
}

.attraction-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
}

.tag-cat      { background: var(--c-primary-bg); color: var(--c-primary); }
.tag-time     { background: #eff6ff; color: #1d4ed8; }
.tag-price    { background: #f0fdf4; color: #15803d; }
.tag-rating   { background: #fffbeb; color: #b45309; }

.edit-controls {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.edit-controls button {
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  padding: 6px 9px;
  transition: background .15s;
}

.edit-controls button:hover { background: var(--c-border); }

.btn-del {
  background: #fee2e2 !important;
  border-color: #fca5a5 !important;
  color: #b91c1c;
}

.btn-del:hover { background: #fca5a5 !important; }

/* ── Weather ── */
.weather-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
}

.weather-card {
  background: linear-gradient(160deg, #f0fdfa, var(--c-surface-2));
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  display: grid;
  gap: 3px;
  padding: 14px;
  text-align: center;
}

.weather-date { color: var(--c-text-3); font-size: 12px; font-weight: 600; }
.weather-icon { font-size: 28px; margin: 4px 0; }
.weather-desc { color: var(--c-text-2); font-size: 13px; }
.weather-temp { color: var(--c-text); font-size: 15px; font-weight: 700; }
.weather-wind { color: var(--c-text-3); font-size: 12px; }

/* ── Agent workflow ── */
.agent-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, 1fr);
}

.agent-card {
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 14px;
}

.agent-header { display: grid; gap: 3px; }

.agent-name {
  color: var(--c-primary);
  font-size: 13px;
  font-weight: 700;
}

.agent-summary {
  color: var(--c-text-2);
  font-size: 12px;
}

.agent-response {
  color: var(--c-text);
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
}

.agent-detail > summary {
  color: var(--c-text-3);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  user-select: none;
}

.agent-trace-body {
  color: var(--c-text-2);
  font-size: 12px;
  line-height: 1.55;
  margin-top: 8px;
}

.agent-trace-body code {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 4px;
  display: block;
  margin-top: 4px;
  overflow-wrap: anywhere;
  padding: 6px 8px;
}

.no-tools { color: var(--c-text-3); font-style: italic; }

/* ── Responsive ── */
@media (max-width: 980px) {
  .result-page {
    grid-template-columns: 1fr;
    padding: 12px;
  }

  .side-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    max-height: none;
    overflow-x: auto;
    padding: 10px;
    position: static;
    width: 100%;
  }

  .nav-title { display: none; }

  .side-nav button,
  .back-link { flex: 0 0 auto; white-space: nowrap; }

  .hero {
    align-items: stretch;
    flex-direction: column;
    gap: 16px;
    padding: 24px 20px 18px;
  }

  .hero-city { font-size: 30px; }
  .hero-actions { flex-direction: row; flex-wrap: wrap; }

  .budget-cards,
  .agent-grid { grid-template-columns: repeat(2, 1fr); }

  .meal-list { grid-template-columns: 1fr; }

  .attraction-card {
    grid-template-columns: 100px minmax(0, 1fr) auto;
  }

  .attraction-img-wrap { width: 100px; }

  .budget-detail-head,
  .budget-detail-row { grid-template-columns: 1fr; min-width: 0; }
}

@media (max-width: 600px) {
  .budget-cards { grid-template-columns: repeat(2, 1fr); }
  .agent-grid { grid-template-columns: 1fr; }
  .attraction-card { grid-template-columns: 1fr; }
  .attraction-img-wrap { width: 100%; }
}
</style>
