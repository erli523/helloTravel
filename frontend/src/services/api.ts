import axios from "axios";

import type {
  AgentTrace,
  IntegrationStatus,
  TravelPlanRequest,
  TravelPlanResponse,
  TripPlan
} from "../types";

export const api = axios.create({
  baseURL: "/api",
  timeout: 420000,
  headers: {
    "Content-Type": "application/json"
  }
});

api.interceptors.request.use(
  (config) => {
    console.info("Sending request:", config.method?.toUpperCase(), config.url);
    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (response) => {
    console.info("Received response:", response.status, response.config.url);
    return response;
  },
  (error) => {
    console.error("Request failed:", error);
    if (axios.isAxiosError(error) && error.code === "ECONNABORTED") {
      return Promise.reject(
        new Error(
          "Planning timed out while waiting for external services. The request kept quality checks enabled; please retry when the network is steadier."
        )
      );
    }
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") {
      return Promise.reject(new Error(detail));
    }
    return Promise.reject(error);
  }
);

export async function generateTripPlan(
  request: TravelPlanRequest
): Promise<TripPlan> {
  const response = await api.post<TravelPlanResponse>("/travel/plans", request);
  return response.data.plan;
}

export async function createTravelPlan(
  request: TravelPlanRequest
): Promise<TravelPlanResponse> {
  const plan = await generateTripPlan(request);
  return { plan };
}

export async function getAgentTraces(): Promise<AgentTrace[]> {
  const response = await api.get<AgentTrace[]>("/travel/agent-traces");
  return response.data;
}

export async function getIntegrationStatus(): Promise<IntegrationStatus> {
  const response = await api.get<IntegrationStatus>("/travel/integrations");
  return response.data;
}
