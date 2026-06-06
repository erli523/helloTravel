import { createRouter, createWebHistory } from "vue-router";

import TripPlannerView from "../views/TripPlannerView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "trip-planner",
      component: TripPlannerView
    }
  ]
});

export default router;
