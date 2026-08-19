import { request, requestForm } from "@/services/client";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];

export function listAssets(projectId?: string) {
  const query = projectId ? `?project_id=${projectId}` : "";
  return request<AssetRead[]>(`/api/v1/assets${query}`);
}

export function getAsset(assetId: string) {
  return request<AssetRead>(`/api/v1/assets/${assetId}`);
}

/** Matches `Body_upload_asset_api_v1_assets_upload_post` exactly:
 * `project_id` and `file` are the only required multipart fields. */
export function uploadAsset(projectId: string, file: File) {
  const form = new FormData();
  form.append("project_id", projectId);
  form.append("file", file);
  return requestForm<AssetRead>("/api/v1/assets/upload", form);
}

export function reprocessAsset(assetId: string) {
  return request<AssetRead>(`/api/v1/assets/${assetId}/process`, { method: "POST" });
}
