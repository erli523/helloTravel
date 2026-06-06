<template>
  <section class="map-preview">
    <header>
      <h2>地图点位</h2>
      <span>{{ points.length }} 个地点</span>
    </header>

    <div class="map-canvas">
      <span
        v-for="(point, index) in points"
        :key="point.name"
        class="map-pin"
        :style="pinStyle(index)"
        :title="point.name"
      >
        {{ index + 1 }}
      </span>
    </div>

    <ol>
      <li v-for="point in points" :key="point.name">
        <strong>{{ point.name }}</strong>
        <span>{{ point.location.longitude.toFixed(3) }}, {{ point.location.latitude.toFixed(3) }}</span>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

import type { TripPlan } from "../types/travel";

const props = defineProps<{
  plan: TripPlan | null;
}>();

const points = computed(() =>
  props.plan
    ? props.plan.days.flatMap((day) => day.attractions)
    : []
);

function pinStyle(index: number) {
  const positions = [
    { left: "22%", top: "34%" },
    { left: "55%", top: "48%" },
    { left: "72%", top: "28%" },
    { left: "38%", top: "66%" }
  ];
  return positions[index % positions.length];
}
</script>

<style scoped>
.map-preview {
  display: grid;
  gap: 14px;
}

header {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

h2 {
  margin: 0;
}

header span {
  color: #64748b;
}

.map-canvas {
  background:
    linear-gradient(90deg, rgba(15, 118, 110, 0.08) 1px, transparent 1px),
    linear-gradient(rgba(15, 118, 110, 0.08) 1px, transparent 1px),
    #f8fafc;
  background-size: 28px 28px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  height: 260px;
  position: relative;
}

.map-pin {
  align-items: center;
  background: #0f766e;
  border-radius: 999px;
  color: white;
  display: inline-flex;
  font-size: 13px;
  font-weight: 700;
  height: 28px;
  justify-content: center;
  position: absolute;
  transform: translate(-50%, -50%);
  width: 28px;
}

ol {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 20px;
}

li {
  color: #475569;
}

li strong {
  color: #0f172a;
  display: block;
}
</style>
