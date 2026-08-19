import { request } from "@/services/client";
import type { components } from "@/types/api";

type HealthResponse = components["schemas"]["HealthResponse"];

/** `/health` has no `/api/v1` prefix and needs no auth header — see
 * `app/modules/health/router.py`: "monitoring should not have to be
 * re-pointed when the API version changes" and "a monitor should not
 * need a credential." */
export function getHealth() {
  return request<HealthResponse>("/health", { auth: false });
}
