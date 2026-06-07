<template>
  <main class="result-page">
    <aside class="side-nav">
      <RouterLink class="back-link" to="/">New plan</RouterLink>
      <div class="nav-title">
        <span>Itinerary</span>
        <strong>{{ tripPlan?.city || "Trip" }}</strong>
      </div>
      <button
        v-for="item in navItems"
        :key="item.key"
        :class="{ active: activeSection === item.key }"
        type="button"
        @click="scrollToSection(item.key)"
      >
        {{ item.label }}
      </button>
    </aside>

    <section v-if="!tripPlan" class="missing-state">
      <h1>No trip plan yet</h1>
      <p>Generate a plan from the home page first.</p>
      <RouterLink to="/">Go to planner</RouterLink>
    </section>

    <section v-else class="result-shell">
      <div class="toolbar">
        <div>
          <p class="eyebrow">{{ tripPlan.start_date }} to {{ tripPlan.end_date }}</p>
          <h1>{{ tripPlan.city }} Travel Plan</h1>
          <div class="quick-stats">
            <span>{{ tripPlan.days.length }} days</span>
            <span>{{ totalAttractions }} attractions</span>
            <span v-if="tripPlan.budget">{{ tripPlan.budget.total }} CNY</span>
          </div>
        </div>
        <div class="toolbar-actions">
          <button type="button" @click="exportAsImage">Export PNG</button>
          <button type="button" @click="exportAsPDF">Export PDF</button>
          <button v-if="!editMode" type="button" @click="enterEditMode">Edit</button>
          <button v-if="editMode" type="button" @click="saveChanges">Save</button>
          <button v-if="editMode" class="secondary" type="button" @click="cancelEdit">
            Cancel
          </button>
        </div>
      </div>

      <div id="trip-plan-content" class="content-stack">
        <section id="overview" class="panel">
          <div class="section-heading">
            <span>01</span>
            <h2>Overview</h2>
          </div>
          <p>{{ tripPlan.overall_suggestions }}</p>
        </section>

        <section v-if="tripPlan.budget" id="budget" class="panel">
          <div class="section-heading">
            <span>02</span>
            <h2>Budget</h2>
          </div>
          <div class="budget-grid">
            <div>
              <span>Attractions</span>
              <strong>{{ tripPlan.budget.total_attractions }} CNY</strong>
            </div>
            <div>
              <span>Hotels</span>
              <strong>{{ tripPlan.budget.total_hotels }} CNY</strong>
            </div>
            <div>
              <span>Meals</span>
              <strong>{{ tripPlan.budget.total_meals }} CNY</strong>
            </div>
            <div>
              <span>Transport</span>
              <strong>{{ tripPlan.budget.total_transportation }} CNY</strong>
            </div>
          </div>
          <div class="total-budget">{{ tripPlan.budget.total }} CNY</div>
          <p class="budget-note">
            Travelers: {{ tripPlan.budget.travelers }} | Hotel nights:
            {{ tripPlan.budget.hotel_nights }}
          </p>
          <div class="budget-detail-table">
            <div class="budget-detail-head">
              <span>Category</span>
              <span>Item</span>
              <span>Unit</span>
              <span>Qty</span>
              <span>Subtotal</span>
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
              <span>{{ detail.unit_cost }} CNY</span>
              <span>{{ detail.quantity }}</span>
              <span>{{ detail.subtotal }} CNY</span>
            </div>
          </div>
        </section>

        <section id="map" class="panel map-panel" :class="{ exporting: isExporting }">
          <div class="section-heading">
            <span>03</span>
            <h2>Map</h2>
          </div>
          <div ref="mapContainer" class="amap-container">
            <span v-if="mapFallback">{{ mapFallback }}</span>
          </div>
        </section>

        <section id="days" class="panel">
          <div class="section-heading">
            <span>04</span>
            <h2>Daily itinerary</h2>
          </div>
          <article v-for="(day, dayIndex) in tripPlan.days" :key="day.date" class="day-card">
            <header>
              <div>
                <span>第 {{ day.day_index + 1 }} 天</span>
                <h3>{{ day.date }}</h3>
              </div>
              <p>{{ day.transportation }}</p>
            </header>
            <p>{{ day.description }}</p>
            <p class="hotel-line">🏨 住宿：{{ day.hotel?.name || day.accommodation }}</p>

            <!-- Detailed time-based timeline -->
            <div v-if="day.timeline && day.timeline.length" class="day-timeline">
              <div
                v-for="(item, ti) in day.timeline"
                :key="`${day.date}-tl-${ti}`"
                :class="['timeline-item', `tl-${item.item_type}`]"
              >
                <div class="tl-time-col">
                  <span class="tl-start">{{ item.time }}</span>
                  <span class="tl-sep">↓</span>
                  <span class="tl-end">{{ item.end_time }}</span>
                </div>
                <div class="tl-track">
                  <div class="tl-dot"></div>
                  <div v-if="ti < day.timeline.length - 1" class="tl-line"></div>
                </div>
                <div class="tl-body">
                  <div class="tl-title">
                    <span class="tl-icon">{{ timelineIcon(item.item_type) }}</span>
                    <strong>{{ item.activity }}</strong>
                  </div>
                  <p v-if="item.notes" class="tl-notes">{{ item.notes }}</p>
                  <small v-if="item.location" class="tl-location">📍 {{ item.location }}</small>
                </div>
              </div>
            </div>

            <!-- Fallback: classic meal list when no timeline -->
            <div v-else class="meal-list">
              <section v-for="meal in day.meals" :key="`${day.date}-${meal.type}-${meal.name}`">
                <span>{{ meal.type }}</span>
                <strong>{{ meal.name }}</strong>
                <p>{{ meal.address || meal.description }}</p>
              </section>
            </div>

            <!-- Attraction photo cards (always shown) -->
            <div class="attractions">
              <section
                v-for="(attraction, attractionIndex) in day.attractions"
                :key="`${day.date}-${attraction.name}`"
                class="attraction-row"
              >
                <img
                  v-if="attraction.image_url"
                  :src="attraction.image_url"
                  :alt="attraction.name"
                  loading="lazy"
                  referrerpolicy="no-referrer"
                  @error="handleImageError(attraction)"
                />
                <div class="image-placeholder" v-else></div>
                <div>
                  <h4>{{ attraction.name }}</h4>
                  <p>{{ attraction.description }}</p>
                  <span>
                    {{ attraction.category }} · {{ attraction.visit_duration }} 分钟 ·
                    {{ attraction.ticket_price > 0 ? attraction.ticket_price + ' 元' : '免费' }}
                    <template v-if="attraction.rating"> · ⭐ {{ attraction.rating }}</template>
                  </span>
                </div>
                <div v-if="editMode" class="edit-buttons">
                  <button type="button" @click="moveAttraction(dayIndex, attractionIndex, 'up')">上移</button>
                  <button type="button" @click="moveAttraction(dayIndex, attractionIndex, 'down')">下移</button>
                  <button type="button" class="danger" @click="deleteAttraction(dayIndex, attractionIndex)">删除</button>
                </div>
              </section>
            </div>
          </article>
        </section>

        <section id="weather" class="panel">
          <div class="section-heading">
            <span>05</span>
            <h2>Weather</h2>
          </div>
          <div class="weather-grid">
            <div v-for="weather in tripPlan.weather_info" :key="weather.date">
              <strong>{{ weather.date }}</strong>
              <span>{{ weather.day_weather }} / {{ weather.night_weather }}</span>
              <span>{{ weather.day_temp }}°C / {{ weather.night_temp }}°C</span>
              <span>{{ weather.wind_direction }} {{ weather.wind_power }}</span>
            </div>
          </div>
        </section>

        <section id="agents" class="panel">
          <div class="section-heading">
            <span>06</span>
            <h2>Agent workflow</h2>
          </div>
          <div class="agent-grid">
            <article v-for="trace in agentTraces" :key="trace.agent_name" class="agent-card">
              <header>
                <span>{{ trace.agent_name }}</span>
                <strong>{{ trace.summary }}</strong>
              </header>
              <p>{{ trace.agent_response || trace.reasoning_summary }}</p>
              <details>
                <summary>Trace</summary>
                <div>
                  <b>Reasoning summary</b>
                  <p>{{ trace.reasoning_summary }}</p>
                </div>
                <div>
                  <b>Tool calls</b>
                  <code v-for="call in trace.tool_calls" :key="call">{{ call }}</code>
                  <span v-if="trace.tool_calls.length === 0">No external tool call.</span>
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
  { key: "overview", label: "Overview" },
  { key: "budget", label: "Budget" },
  { key: "map", label: "Map" },
  { key: "days", label: "Daily itinerary" },
  { key: "weather", label: "Weather" },
  { key: "agents", label: "Agent workflow" }
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

async function initMap() {
  const points = allAttractions();
  if (!mapContainer.value || points.length === 0) {
    mapFallback.value = "No attraction coordinates available.";
    return;
  }

  const key = import.meta.env.VITE_AMAP_WEB_KEY as string | undefined;
  if (!key) {
    mapFallback.value = "Set VITE_AMAP_WEB_KEY to enable Amap JS map.";
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
    mapFallback.value = "Map failed to load. Coordinates are still listed in the itinerary.";
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
  const imgWidth = 210;
  const imgHeight = (canvas.height * imgWidth) / canvas.width;
  pdf.addImage(imgData, "PNG", 0, 0, imgWidth, imgHeight);
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
.result-page {
  background:
    linear-gradient(180deg, #eaf4f1 0%, #f8fafc 42%, #f7f3ea 100%);
  color: #0f172a;
  display: grid;
  gap: 20px;
  grid-template-columns: 216px minmax(0, 1fr);
  min-height: 100vh;
  overflow-x: hidden;
  padding: 20px;
  width: 100%;
}

.side-nav,
.panel,
.toolbar,
.missing-state {
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.06);
}

.side-nav {
  align-self: start;
  display: grid;
  gap: 8px;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  padding: 12px;
  position: sticky;
  top: 20px;
  width: 216px;
}

.nav-title {
  border-bottom: 1px solid #e2e8f0;
  display: grid;
  gap: 3px;
  margin-bottom: 4px;
  padding: 4px 4px 12px;
}

.nav-title span,
.eyebrow {
  color: #0f766e;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.nav-title strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-nav button,
.back-link,
.toolbar-actions button,
.edit-buttons button {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #0f172a;
  cursor: pointer;
  font: inherit;
  min-width: 0;
  padding: 9px 10px;
  text-align: left;
  text-decoration: none;
  transition:
    background 0.18s ease,
    border-color 0.18s ease,
    color 0.18s ease,
    transform 0.18s ease;
}

.side-nav button,
.back-link {
  background: #f8fafc;
  overflow-wrap: anywhere;
}

.back-link {
  background: #0f766e;
  border-color: #0f766e;
  color: #ffffff;
  font-weight: 800;
  text-align: center;
}

.side-nav button:hover,
.toolbar-actions button:hover,
.edit-buttons button:hover {
  transform: translateY(-1px);
}

.side-nav button.active,
.toolbar-actions button:not(.secondary),
.edit-buttons button:not(.danger) {
  background: #0f766e;
  border-color: #0f766e;
  color: #ffffff;
}

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

.toolbar {
  align-items: center;
  display: flex;
  gap: 18px;
  justify-content: space-between;
  min-width: 0;
  padding: 20px;
}

.toolbar h1,
.toolbar p,
.panel h2,
.day-card h3,
.attraction-row h4 {
  margin: 0;
}

.toolbar h1 {
  font-size: 32px;
  line-height: 1.1;
}

.eyebrow {
  margin-bottom: 7px;
}

.quick-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.quick-stats span {
  background: #eef6f4;
  border: 1px solid #cce3df;
  border-radius: 8px;
  color: #115e59;
  font-size: 13px;
  font-weight: 800;
  padding: 7px 9px;
}

.toolbar p,
.day-card header p,
.hotel-line,
.attraction-row p,
.weather-grid span {
  color: #475569;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  min-width: 220px;
}

.toolbar-actions button {
  background: #ffffff;
  text-align: center;
}

.panel,
.missing-state {
  min-width: 0;
  padding: 20px;
}

.section-heading {
  align-items: center;
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.section-heading span {
  align-items: center;
  background: #102a43;
  border-radius: 8px;
  color: #ffffff;
  display: inline-flex;
  font-size: 12px;
  font-weight: 900;
  height: 30px;
  justify-content: center;
  width: 36px;
}

.section-heading h2 {
  font-size: 22px;
  line-height: 1.1;
}

.budget-grid,
.weather-grid,
.agent-grid {
  display: grid;
  gap: 10px;
}

.budget-grid,
.weather-grid {
  grid-template-columns: repeat(4, minmax(140px, 1fr));
}

.budget-grid div,
.weather-grid div {
  background: linear-gradient(180deg, #ffffff, #f8fafc);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: grid;
  gap: 5px;
  padding: 12px;
}

.agent-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.agent-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
}

.agent-card header {
  display: grid;
  gap: 4px;
}

.agent-card header span {
  color: #0f766e;
  font-size: 13px;
  font-weight: 800;
}

.agent-card p {
  margin: 0;
}

.agent-card details {
  color: #475569;
}

.agent-card code {
  background: #e2e8f0;
  border-radius: 6px;
  display: block;
  margin-top: 6px;
  max-width: 100%;
  overflow-wrap: anywhere;
  padding: 7px;
}

.budget-grid span {
  color: #64748b;
  font-size: 13px;
}

.total-budget {
  color: #0f766e;
  font-size: 32px;
  font-weight: 800;
  margin-top: 14px;
  text-align: center;
}

.budget-note {
  color: #475569;
  margin: 8px 0 0;
  text-align: center;
}

.budget-detail-table {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: grid;
  margin-top: 14px;
  max-width: 100%;
  overflow-x: auto;
}

.budget-detail-head,
.budget-detail-row {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(86px, 0.75fr) minmax(220px, 2fr) minmax(82px, 0.7fr) minmax(52px, 0.45fr) minmax(92px, 0.75fr);
  min-width: 640px;
  padding: 10px 12px;
}

.budget-detail-head {
  background: #0f766e;
  color: #ffffff;
  font-weight: 800;
}

.budget-detail-row {
  align-items: center;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
}

.budget-detail-row span,
.budget-detail-head span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.budget-detail-row small {
  color: #64748b;
  display: block;
  margin-top: 3px;
}

.amap-container {
  align-items: center;
  background:
    linear-gradient(90deg, rgba(15, 118, 110, 0.08) 1px, transparent 1px),
    linear-gradient(rgba(15, 118, 110, 0.08) 1px, transparent 1px),
    #f8fafc;
  background-size: 28px 28px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  display: flex;
  height: 340px;
  justify-content: center;
  margin-top: 12px;
  overflow: hidden;
}

.map-panel.exporting {
  display: none;
}

.day-card {
  border-top: 1px solid #e2e8f0;
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 16px 0;
}

.day-card header {
  align-items: start;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.day-card header span {
  color: #64748b;
  font-size: 13px;
}

.attractions {
  display: grid;
  gap: 12px;
}

.meal-list {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  min-width: 0;
}

.meal-list section {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
}

.meal-list span {
  color: #c2410c;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.meal-list strong,
.meal-list p {
  margin: 0;
}

.meal-list p {
  color: #7c2d12;
  font-size: 13px;
}

/* ── Day timeline ─────────────────────────────────────────────────── */
.day-timeline {
  display: flex;
  flex-direction: column;
  margin: 4px 0 8px;
}

.timeline-item {
  display: grid;
  grid-template-columns: 58px 22px 1fr;
  gap: 0 10px;
  min-height: 52px;
}

.tl-time-col {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding-top: 2px;
  gap: 1px;
  min-width: 0;
}

.tl-start {
  font-weight: 700;
  font-size: 13px;
  color: #1e293b;
  white-space: nowrap;
}

.tl-sep {
  font-size: 10px;
  color: #cbd5e1;
  line-height: 1;
}

.tl-end {
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
}

.tl-track {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 4px;
}

.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #3b82f6;
  flex-shrink: 0;
}

.tl-line {
  width: 2px;
  flex: 1;
  background: #e2e8f0;
  min-height: 14px;
  margin: 3px 0;
}

.tl-body {
  padding: 0 0 14px;
  min-width: 0;
}

.tl-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}

.tl-icon {
  font-size: 15px;
  flex-shrink: 0;
}

.tl-notes {
  font-size: 12px;
  color: #64748b;
  margin: 3px 0 0;
  line-height: 1.55;
}

.tl-location {
  font-size: 11px;
  color: #94a3b8;
  display: block;
  margin-top: 2px;
}

/* Type-specific dot colours */
.tl-attraction .tl-dot { background: #3b82f6; }
.tl-meal .tl-dot       { background: #22c55e; }
.tl-transit .tl-dot    { background: #94a3b8; }
.tl-rest .tl-dot       { background: #f97316; }

.tl-transit .tl-title strong {
  color: #64748b;
  font-weight: 500;
}

.tl-rest .tl-title strong {
  color: #ea580c;
}

.attraction-row {
  align-items: start;
  background: #fbfdff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: grid;
  gap: 12px;
  grid-template-columns: 124px minmax(0, 1fr) auto;
  min-width: 0;
  padding: 10px;
}

.attraction-row img,
.image-placeholder {
  aspect-ratio: 4 / 3;
  border-radius: 8px;
  object-fit: cover;
  width: 124px;
}

.attraction-row > div {
  min-width: 0;
}

.attraction-row h4,
.attraction-row p,
.hotel-line,
.day-card > p {
  overflow-wrap: anywhere;
}

.image-placeholder {
  background:
    linear-gradient(135deg, rgba(15, 118, 110, 0.16), rgba(245, 158, 11, 0.14)),
    #dbe7e4;
}

.attraction-row span {
  color: #0f766e;
  font-size: 13px;
}

.edit-buttons {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
}

.edit-buttons button {
  padding: 7px 9px;
  text-align: center;
}

.edit-buttons .danger {
  background: #b91c1c;
  border-color: #b91c1c;
  color: #ffffff;
}

@media (max-width: 980px) {
  .result-page {
    grid-template-columns: 1fr;
    padding: 12px;
  }

  .side-nav {
    display: flex;
    gap: 8px;
    max-height: none;
    overflow-x: auto;
    padding: 10px;
    position: static;
    width: 100%;
  }

  .nav-title {
    display: none;
  }

  .side-nav button,
  .back-link {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  .budget-grid,
  .weather-grid,
  .agent-grid,
  .meal-list,
  .attraction-row {
    grid-template-columns: 1fr;
  }

  .toolbar,
  .day-card header {
    align-items: stretch;
    display: grid;
  }

  .budget-detail-head,
  .budget-detail-row {
    grid-template-columns: 1fr;
    min-width: 0;
  }

  .toolbar-actions {
    justify-content: stretch;
    min-width: 0;
  }

  .toolbar-actions button {
    flex: 1 1 140px;
  }

  .attraction-row img,
  .image-placeholder {
    width: 100%;
  }
}
</style>
