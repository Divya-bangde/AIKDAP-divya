import { request } from "@/services/client";
import type { components } from "@/types/api";

type ResearchRunCreate = components["schemas"]["ResearchRunCreate"];
type ResearchRunAccepted = components["schemas"]["ResearchRunAccepted"];
type ResearchRunDetail = components["schemas"]["ResearchRunDetail"];
type ResearchRunRead = components["schemas"]["ResearchRunRead"];

export function startResearchRun(payload: ResearchRunCreate) {
  return request<ResearchRunAccepted>("/api/v1/research/run", {
    method: "POST",
    body: payload,
  });
}

export function getResearchRun(runId: string) {
  return request<ResearchRunDetail>(`/api/v1/research/runs/${runId}`);
}

export function listResearchRuns(projectId?: string) {
  const query = projectId ? `?project_id=${projectId}` : "";
  return request<ResearchRunRead[]>(`/api/v1/research/runs${query}`);
}
