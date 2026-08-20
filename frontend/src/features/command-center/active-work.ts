import { isSettled } from "@/features/assets/asset-state";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];
type ProjectRead = components["schemas"]["ProjectRead"];
type ResearchRunRead = components["schemas"]["ResearchRunRead"];

const ACTIVE_RUN_STATUSES = new Set(["pending", "running"]);

/** One thing AIKDAP is genuinely doing right now, not something that
 * happened recently. A research run counts while its own `status` is
 * `pending`/`running` — never inferred from elapsed time. A document
 * counts while `isSettled` says no (the same real, backend-reported
 * state `usePolling` already uses to decide whether to keep polling),
 * so "active" here means exactly "this page would still be polling
 * for it". */
export interface ActiveWorkItem {
  kind: "research" | "document";
  id: string;
  label: string;
  projectId: string;
  /** `undefined` when the owning project hasn't loaded (or failed to)
   * — rendered as nothing, never as a guessed name. */
  projectName: string | undefined;
  status: string;
  /** Which `StatusBadge` vocabulary `status` belongs to — a document's
   * genuinely-still-pending step is not always `processing_status`
   * (see below), so the badge domain has to travel with the value it
   * labels rather than being inferred from `kind` alone. */
  statusDomain: "researchRun" | "assetProcessing" | "aiProfile" | "embedding";
  updatedAt: string;
}

/** The one field of a not-yet-settled document that is actually still
 * pending, with the badge vocabulary it belongs to.
 *
 * `processing_status` reaching `"completed"` does not mean the asset
 * has settled — understanding and embedding are separate state
 * machines that can still be running behind it (documented at length
 * on `isSettled`, which this mirrors). Showing `processing_status`
 * unconditionally would have rendered a "Completed" badge on a row
 * this panel is presenting as in-progress work — confirmed live: a
 * real document sat in Active Work captioned "Completed" the moment
 * extraction finished but embedding hadn't, which reads as a
 * contradiction rather than as the accurate mid-pipeline state it is. */
function pendingDocumentStatus(
  asset: AssetRead,
): Pick<ActiveWorkItem, "status" | "statusDomain"> {
  if (asset.processing_status !== "completed") {
    return { status: asset.processing_status, statusDomain: "assetProcessing" };
  }
  if (asset.ai_profile.status !== "completed") {
    return { status: asset.ai_profile.status, statusDomain: "aiProfile" };
  }
  return { status: asset.ai_profile.embedding_status, statusDomain: "embedding" };
}

/** Real in-flight work across every project, newest first.
 *
 * Built entirely from data the Command Center already fetches — no
 * new request. Pure and independent of React so it can be tested
 * directly against fixture arrays, the same pattern `knowledgeState`
 * and `evidenceFunnel` already use. */
export function activeWork(
  runs: ResearchRunRead[],
  assets: AssetRead[],
  projects: ProjectRead[],
): ActiveWorkItem[] {
  const projectNames = new Map(projects.map((project) => [project.id, project.name]));

  const runItems: ActiveWorkItem[] = runs
    .filter((run) => ACTIVE_RUN_STATUSES.has(run.status))
    .map((run) => ({
      kind: "research",
      id: run.id,
      label: run.query,
      projectId: run.project_id,
      projectName: projectNames.get(run.project_id),
      status: run.status,
      statusDomain: "researchRun",
      updatedAt: run.updated_at,
    }));

  const assetItems: ActiveWorkItem[] = assets
    .filter((asset) => !isSettled(asset))
    .map((asset) => ({
      kind: "document",
      id: asset.id,
      label: asset.title,
      projectId: asset.project_id,
      projectName: projectNames.get(asset.project_id),
      ...pendingDocumentStatus(asset),
      updatedAt: asset.updated_at,
    }));

  return [...runItems, ...assetItems].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}
