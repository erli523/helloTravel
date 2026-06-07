<template>
  <main class="result-page">
    <aside class="side-nav">
      <RouterLink class="back-link" to="/">New plan</RouterLink>
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
          <p>{{ tripPlan.start_date }} to {{ tripPlan.end_date }}</p>
          <h1>{{ tripPlan.city }} Travel Plan</h1>
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
          <h2>Overview</h2>
          <p>{{ tripPlan.overall_suggestions }}</p>
        </section>

        <section v-if="tripPlan.budget" id="budget" class="panel">
          <h2>Budget</h2>
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
        </section>

        <section id="map" class="panel map-panel" :class="{ exporting: isExporting }">
          <h2>Map</h2>
          <div ref="mapContainer" class="amap-container">
            <span v-if="mapFallback">{{ mapFallback }}</span>
          </div>
        </section>

        <section id="days" class="panel">
          <h2>Daily itinerary</h2>
          <article v-for="(day, dayIndex) in tripPlan.days" :key="day.date" class="day-card">
            <header>
              <div>
                <span>Day {{ day.day_index + 1 }}</span>
                <h3>{{ day.date }}</h3>
              </div>
              <p>{{ day.transportation }}</p>
            </header>
            <p>{{ day.description }}</p>
            <p class="hotel-line">Hotel: {{ day.hotel?.name || day.accommodation }}</p>

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
                    {{ attraction.category }} · {{ attraction.visit_duration }} min ·
                    {{ attraction.ticket_price }} CNY
                  </span>
                </div>
                <div v-if="editMode" class="edit-buttons">
                  <button type="button" @click="moveAttraction(dayIndex, attractionIndex, 'up')">
                    Up
                  </button>
                  <button type="button" @click="moveAttraction(dayIndex, attractionIndex, 'down')">
                    Down
                  </button>
                  <button type="button" class="danger" @click="deleteAttraction(dayIndex, attractionIndex)">
                    Delete
                  </button>
                </div>
              </section>
            </div>
          </article>
        </section>

        <section id="weather" class="panel">
          <h2>Weather</h2>
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
          <h2>Agent workflow</h2>
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
import { nextTick, onMounted, ref } from "vue";

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
  background: #eef6f4;
  color: #0f172a;
  display: grid;
  gap: 22px;
  grid-template-columns: 220px 1fr;
  min-height: 100vh;
  padding: 22px;
}

.side-nav,
.panel,
.toolbar,
.missing-state {
  background: #ffffff;
  border: 1px solid #dbe7e4;
  border-radius: 8px;
}

.side-nav {
  align-self: start;
  display: grid;
  gap: 8px;
  padding: 14px;
  position: sticky;
  top: 22px;
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
  padding: 9px 10px;
  text-align: left;
  text-decoration: none;
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
}

.toolbar {
  align-items: center;
  display: flex;
  gap: 18px;
  justify-content: space-between;
  padding: 18px;
}

.toolbar h1,
.toolbar p,
.panel h2,
.day-card h3,
.attraction-row h4 {
  margin: 0;
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
}

.toolbar-actions button {
  text-align: center;
}

.panel,
.missing-state {
  padding: 18px;
}

.budget-grid,
.weather-grid,
.agent-grid {
  display: grid;
  gap: 10px;
}

.budget-grid,
.weather-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.budget-grid div,
.weather-grid div {
  background: #f8fafc;
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
  height: 320px;
  justify-content: center;
  margin-top: 12px;
}

.map-panel.exporting {
  display: none;
}

.day-card {
  border-top: 1px solid #e2e8f0;
  display: grid;
  gap: 12px;
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

.attraction-row {
  align-items: center;
  display: grid;
  gap: 12px;
  grid-template-columns: 110px 1fr auto;
}

.attraction-row img,
.image-placeholder {
  aspect-ratio: 4 / 3;
  border-radius: 8px;
  object-fit: cover;
  width: 110px;
}

.image-placeholder {
  background: #dbe7e4;
}

.attraction-row span {
  color: #0f766e;
  font-size: 13px;
}

.edit-buttons {
  display: flex;
  gap: 6px;
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
  }

  .side-nav {
    position: static;
  }

  .budget-grid,
  .weather-grid,
  .agent-grid,
  .attraction-row {
    grid-template-columns: 1fr;
  }

  .toolbar,
  .day-card header {
    align-items: stretch;
    display: grid;
  }
}
</style>
