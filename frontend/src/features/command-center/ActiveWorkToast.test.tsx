import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActiveWorkToast } from "@/features/command-center/ActiveWorkToast";
import * as assetsService from "@/services/assets";
import * as projectsService from "@/services/projects";
import * as researchService from "@/services/research";
import { aiProfile, makeAsset, makeProject, makeRun } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";

vi.mock("@/services/assets");
vi.mock("@/services/projects");
vi.mock("@/services/research");

describe("ActiveWorkToast", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders nothing when every run and document has settled", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([makeAsset()]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([makeRun()]);

    renderWithProviders(<ActiveWorkToast />);

    await waitFor(() => expect(researchService.listResearchRuns).toHaveBeenCalled());
    expect(screen.queryByRole("status", { name: "Active work" })).not.toBeInTheDocument();
  });

  it("surfaces an in-flight research run, attributed to its real project", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([
      makeProject({ id: "p1", name: "Poultry Intelligence" }),
    ]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([
      makeRun({ status: "running", query: "What is driving feed cost inflation?" }),
    ]);

    renderWithProviders(<ActiveWorkToast />);

    expect(await screen.findByText("What is driving feed cost inflation?")).toBeInTheDocument();
    expect(await screen.findByText("Poultry Intelligence")).toBeInTheDocument();
  });

  it("surfaces a document that hasn't finished its pipeline, not a settled one", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([
      makeAsset({
        title: "still-embedding.pdf",
        ai_profile: aiProfile({ status: "completed", embedding_status: "processing" }),
      }),
      makeAsset({ id: "a2", title: "already-done.pdf" }),
    ]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([]);

    renderWithProviders(<ActiveWorkToast />);

    expect(await screen.findByText("still-embedding.pdf")).toBeInTheDocument();
    expect(screen.queryByText("already-done.pdf")).not.toBeInTheDocument();
  });

  it("can be dismissed", async () => {
    vi.mocked(projectsService.listProjects).mockResolvedValue([makeProject()]);
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);
    vi.mocked(researchService.listResearchRuns).mockResolvedValue([makeRun({ status: "pending" })]);
    const user = userEvent.setup();

    renderWithProviders(<ActiveWorkToast />);
    await user.click(await screen.findByRole("button", { name: /dismiss active work/i }));

    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Active work" })).not.toBeInTheDocument(),
    );
  });
});
