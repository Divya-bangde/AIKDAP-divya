import { describe, expect, it } from "vitest";

import { activeWork } from "@/features/command-center/active-work";
import type { components } from "@/types/api";

type AssetRead = components["schemas"]["AssetRead"];
type ProjectRead = components["schemas"]["ProjectRead"];
type ResearchRunRead = components["schemas"]["ResearchRunRead"];

function project(overrides: Partial<ProjectRead> = {}): ProjectRead {
  return {
    id: "p1",
    owner_id: "u1",
    name: "Project One",
    description: null,
    project_type: "research",
    status: "active",
    color: null,
    icon: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as ProjectRead;
}

function run(overrides: Partial<ResearchRunRead> = {}): ResearchRunRead {
  return {
    id: "r1",
    project_id: "p1",
    owner_id: "u1",
    task_id: null,
    query: "What challenges does the project face?",
    status: "running",
    include_assets: true,
    include_web: false,
    max_results: 5,
    objective: null,
    plan: null,
    final_answer: null,
    citations: null,
    grounding_status: null,
    error_message: null,
    celery_task_id: null,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    duration_ms: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as ResearchRunRead;
}

function asset(overrides: Partial<AssetRead> = {}): AssetRead {
  return {
    id: "a1",
    project_id: "p1",
    owner_id: "u1",
    title: "report.pdf",
    description: null,
    asset_type: "document",
    status: "active",
    mime_type: "application/pdf",
    file_name: "report.pdf",
    file_extension: "pdf",
    file_size: 1024,
    checksum: "abc",
    source: "upload",
    version: 1,
    tags: [],
    metadata: {},
    ai_profile: { status: "pending", embedding_status: "pending" },
    created_by: null,
    processing_status: "extracting",
    processing_error: null,
    processing_started_at: "2026-01-01T00:00:00Z",
    processing_completed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as AssetRead;
}

describe("activeWork", () => {
  it("includes a research run only while it is pending or running", () => {
    const projects = [project()];
    expect(activeWork([run({ status: "pending" })], [], projects)).toHaveLength(1);
    expect(activeWork([run({ status: "running" })], [], projects)).toHaveLength(1);
    expect(activeWork([run({ status: "completed" })], [], projects)).toHaveLength(0);
    expect(activeWork([run({ status: "failed" })], [], projects)).toHaveLength(0);
    expect(activeWork([run({ status: "cancelled" })], [], projects)).toHaveLength(0);
  });

  it("includes a document only while it has not settled", () => {
    const projects = [project()];
    // Still extracting — genuinely in flight.
    expect(activeWork([], [asset({ processing_status: "extracting" })], projects)).toHaveLength(1);
    // Extraction finished but the AI profile hasn't (the real Sprint
    // 9K bug this decoupled check exists to catch).
    expect(
      activeWork(
        [],
        [
          asset({
            processing_status: "completed",
            ai_profile: { status: "pending", embedding_status: "pending" },
          }),
        ],
        projects,
      ),
    ).toHaveLength(1);
    // Fully settled — not active work, even though it's still visible
    // elsewhere in the product.
    expect(
      activeWork(
        [],
        [
          asset({
            processing_status: "completed",
            ai_profile: { status: "completed", embedding_status: "completed" },
          }),
        ],
        projects,
      ),
    ).toHaveLength(0);
  });

  it("shows the genuinely pending step, not a stale 'completed' from an earlier stage", () => {
    const projects = [project()];

    // Still extracting: the honest status is the processing step itself.
    const [extracting] = activeWork(
      [],
      [asset({ processing_status: "extracting" })],
      projects,
    );
    expect(extracting).toMatchObject({ status: "extracting", statusDomain: "assetProcessing" });

    // Extraction finished, understanding hasn't: showing
    // `processing_status` here would render "Completed" on a row this
    // panel presents as active work — confirmed live before this test
    // was written.
    const [understanding] = activeWork(
      [],
      [
        asset({
          processing_status: "completed",
          ai_profile: { status: "pending", embedding_status: "pending" },
        }),
      ],
      projects,
    );
    expect(understanding).toMatchObject({ status: "pending", statusDomain: "aiProfile" });

    // Understanding finished, embedding hasn't.
    const [embedding] = activeWork(
      [],
      [
        asset({
          processing_status: "completed",
          ai_profile: { status: "completed", embedding_status: "processing" },
        }),
      ],
      projects,
    );
    expect(embedding).toMatchObject({ status: "processing", statusDomain: "embedding" });
  });

  it("attaches the real project name by id, never a guess", () => {
    const projects = [project({ id: "p1", name: "Poultry Intelligence" })];
    const [item] = activeWork([run({ project_id: "p1" })], [], projects);
    expect(item.projectName).toBe("Poultry Intelligence");
  });

  it("leaves projectName undefined rather than fabricating one when the project hasn't loaded", () => {
    const [item] = activeWork([run({ project_id: "missing" })], [], []);
    expect(item.projectName).toBeUndefined();
  });

  it("orders the newest update first, mixing runs and documents", () => {
    const projects = [project()];
    const older = run({ id: "r-old", updated_at: "2026-01-01T00:00:00Z" });
    const newer = asset({ id: "a-new", updated_at: "2026-01-02T00:00:00Z" });
    const result = activeWork([older], [newer], projects);
    expect(result.map((item) => item.id)).toEqual(["a-new", "r-old"]);
  });

  it("returns an empty list when nothing is in flight", () => {
    const projects = [project()];
    expect(
      activeWork(
        [run({ status: "completed" })],
        [asset({ processing_status: "completed", ai_profile: { status: "completed", embedding_status: "completed" } })],
        projects,
      ),
    ).toEqual([]);
  });
});
