import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "@/pages/Dashboard";
import * as assetsService from "@/services/assets";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";
import { makeAsset, makeProject, makeRun } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";

vi.mock("@/services/assets");
vi.mock("@/services/projects");
vi.mock("@/services/research");

describe("Dashboard — Recent Research Runs", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the project and duration for a completed run", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([
      makeProject({ id: "p1", name: "Poultry Intelligence" }),
    ]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([
      makeRun({ duration_ms: 4200 }),
    ]);

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText("What challenges does ABC Poultry face?")).toBeInTheDocument();
    // Once as a project entry, once as this run's attribution.
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

  it("shows the run's real outcome, not just that the job finished", async () => {
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
    await screen.findByText("What challenges does ABC Poultry face?");

    /* Motion gives anything carrying `whileTap` a `tabIndex` of 0, so
     * the KPI tiles and card wrappers used to be focusable while doing
     * nothing on Enter (Sprint 9K.6). Every positive-tabindex element
     * must be a real control, or contain one. */
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
