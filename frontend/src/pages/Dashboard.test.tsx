import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "@/pages/Dashboard";
import * as assetsService from "@/services/assets";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";
import { renderWithProviders } from "@/test/render";
import type { components } from "@/types/api";

vi.mock("@/services/assets");
vi.mock("@/services/projects");
vi.mock("@/services/research");

type AssetRead = components["schemas"]["AssetRead"];
type ProjectRead = components["schemas"]["ProjectRead"];
type ResearchRunRead = components["schemas"]["ResearchRunRead"];

function makeProject(overrides: Partial<ProjectRead> = {}): ProjectRead {
  return {
    id: "p1",
    owner_id: "u1",
    name: "Poultry Intelligence",
    description: null,
    project_type: "research",
    status: "active",
    color: null,
    icon: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeRun(overrides: Partial<ResearchRunRead> = {}): ResearchRunRead {
  return {
    id: "r1",
    project_id: "p1",
    owner_id: "u1",
    task_id: null,
    query: "What challenges does ABC Poultry face?",
    status: "completed",
    include_assets: true,
    include_web: false,
    max_results: 5,
    objective: null,
    plan: null,
    final_answer: "Two challenges.",
    citations: [],
    grounding_status: "grounded",
    error_message: null,
    celery_task_id: null,
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    duration_ms: 4200,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeAsset(overrides: Partial<AssetRead> = {}): AssetRead {
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
    ai_profile: { status: "completed", embedding_status: "completed" },
    created_by: null,
    processing_status: "completed",
    processing_error: null,
    processing_started_at: null,
    processing_completed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("Dashboard — Active Work", () => {
  afterEach(() => vi.restoreAllMocks());

  it("says nothing is running when every run and document has settled", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([makeAsset()]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([makeRun()]);

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText("Active Work")).toBeInTheDocument();
    expect(
      await screen.findByText(/nothing running right now/i),
    ).toBeInTheDocument();
  });

  it("surfaces a genuinely in-flight research run, attributed to its real project", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([
      makeProject({ id: "p1", name: "Poultry Intelligence" }),
    ]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([
      makeRun({ status: "running", query: "What is driving feed cost inflation?" }),
    ]);

    renderWithProviders(<Dashboard />);

    // A running run is legitimately both "active work" and "recent" —
    // it appears in both sections, so this asserts presence, not a
    // single node.
    expect(
      (await screen.findAllByText("What is driving feed cost inflation?")).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Poultry Intelligence").length).toBeGreaterThan(0);
    expect(screen.queryByText(/nothing running right now/i)).not.toBeInTheDocument();
  });

  it("surfaces a document that hasn't finished its pipeline, not a settled one", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([
      makeAsset({
        title: "still-embedding.pdf",
        processing_status: "completed",
        ai_profile: { status: "completed", embedding_status: "processing" },
      }),
      makeAsset({ id: "a2", title: "already-done.pdf" }),
    ]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([]);

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText("still-embedding.pdf")).toBeInTheDocument();
    expect(screen.queryByText("already-done.pdf")).not.toBeInTheDocument();
  });

  it("shows the project and duration for a completed run in Recent Research Runs", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([
      makeProject({ id: "p1", name: "Poultry Intelligence" }),
    ]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([
      makeRun({ duration_ms: 4200 }),
    ]);

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText("What challenges does ABC Poultry face?")).toBeInTheDocument();
    // "Poultry Intelligence" now appears twice on the page — once as a
    // real project entry, once as this run's attribution — so this
    // assertion is on the set, not a single node.
    expect(screen.getAllByText("Poultry Intelligence").length).toBeGreaterThan(0);
    expect(screen.getByText("4.2 s")).toBeInTheDocument();
  });

  it("shows a real citation count on a grounded run, never a fabricated one (Sprint 9K.9)", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([
      makeRun({ citations: [{ id: "c1" }], grounding_status: "grounded" }),
    ]);

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText(/1 citation\b/)).toBeInTheDocument();
  });

  it("never claims a citation count for a run that has none", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([
      makeRun({ citations: [], grounding_status: "grounded" }),
    ]);

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText("What challenges does ABC Poultry face?")).toBeInTheDocument();
    expect(screen.queryByText(/citation/)).not.toBeInTheDocument();
  });

  it("shows the run's real outcome in Recent Research Runs, not just that the job finished", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([
      makeRun({ grounding_status: "insufficient_evidence" }),
    ]);

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText("Insufficient Evidence")).toBeInTheDocument();
    expect(screen.queryByText("Completed")).not.toBeInTheDocument();
  });
});

describe("Dashboard — keyboard focus order", () => {
  afterEach(() => vi.restoreAllMocks());

  it("puts no inert stops in the tab order", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([makeAsset()]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([makeRun()]);

    const { container } = renderWithProviders(<Dashboard />);
    await screen.findByText("Active Work");

    /* Motion gives anything carrying `whileTap` a `tabIndex` of 0, so
     * the four KPI tiles and every card wrapper used to be focusable
     * while doing nothing on Enter — five dead stops on this page,
     * counted in a real browser (Sprint 9K.6).
     *
     * `hoverLift` now opts those wrappers out. What must remain true is
     * that nothing reachable by Tab is inert: every positive-tabindex
     * element is a real control, or contains one. */
    const focusable = [...container.querySelectorAll("[tabindex]")].filter(
      (el) => Number(el.getAttribute("tabindex")) >= 0,
    );

    for (const el of focusable) {
      const isControl = ["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
      const hasRole = el.getAttribute("role") !== null;
      expect(
        isControl || hasRole,
        `${el.tagName}.${el.className} is focusable but is not a control`,
      ).toBe(true);
    }
  });
});
