import type { TravelPlanRequest, TravelPlanResponse } from "../types/travel";

const API_BASE_URL = "/api";

export async function createTravelPlan(
  request: TravelPlanRequest
): Promise<TravelPlanResponse> {
  const response = await fetch(`${API_BASE_URL}/travel/plans`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(request)
  });

  if (!response.ok) {
    throw new Error("行程规划请求失败，请稍后重试");
  }

  return response.json();
}

export { API_BASE_URL };
