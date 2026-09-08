import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvidenceGapPanel } from "@/features/research/EvidenceGapPanel";
import * as assetsService from "@/services/assets";
import * as researchService from "@/services/research";
import { renderWithProviders } from "@/test/render";
import type { components } from "@/types/api";

vi.mock("@/services/assets");
vi.mock("@/services/research");

type AssetRead = components["schemas"]["AssetRead"];
type ResearchDocumentUnderstanding = components["schemas"]["ResearchDocumentUnderstanding"];

function makeAsset(): AssetRead {
  return {
    id: "asset-1",
    project_id: "project-1",
    owner_id: "owner-1",
    title: "doc",
    description: null,
    asset_type: "other",
    status: "active",
    mime_type: "application/pdf",
    file_name: "paper.pdf",
    file_extension: ".pdf",
    file_size: 2048,
    checksum: "abc",
    source: "upload",
    version: 1,
    tags: [],
    metadata: {},
    ai_profile: { embedding_status: "completed", status: "completed" },
    created_by: null,
    processing_status: "completed",
    processing_error: null,
    processing_started_at: null,
    processing_completed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

describe("EvidenceGapPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("renders only the real gaps analysis.py returned, with the reason and classification badges", async () => {
    vi.mocked(assetsService.listAssets).mockResolvedValue([makeAsset()]);
    const analysis: ResearchDocumentUnderstanding = {
      title: "paper",
      objectives: [],
      research_questions: [],
      models: [],
      algorithms: [],
      equations: [],
      variables: [],
      evaluation_metrics: [],
      limitations: [],
      future_work: [],
      explicit_assumptions: [],
      missing_information: [
        {
          gap_type: "Detection rate for the specific traffic channel asked about",
          classification: "required",
          description: "The paper does not report a rate for this exact channel.",
          why_needed: "The question asks for a number the source never states.",
        },
      ],
      conflicts: [],
      sufficiency: "insufficient",
      sufficiency_reason: "The retrieved evidence does not name this specific channel.",
    };
    vi.mocked(researchService.analyzeResearchDocument).mockResolvedValue(analysis);

    renderWithProviders(
      <EvidenceGapPanel projectId="project-1" query="What rate did it achieve against X?" />,
    );

    expect(
      await screen.findByText("The retrieved evidence does not name this specific channel."),
    ).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(
      screen.getByText("Detection rate for the specific traffic channel asked about"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The question asks for a number the source never states\./),
    ).toBeInTheDocument();
  });

  it("shows the honest empty state, not invented gap text, when analysis found nothing specific", async () => {
    vi.mocked(assetsService.listAssets).mockResolvedValue([makeAsset()]);
    vi.mocked(researchService.analyzeResearchDocument).mockResolvedValue({
      title: "paper",
      objectives: [],
      research_questions: [],
      models: [],
      algorithms: [],
      equations: [],
      variables: [],
      evaluation_metrics: [],
      limitations: [],
      future_work: [],
      explicit_assumptions: [],
      missing_information: [],
      conflicts: [],
      sufficiency: "partially_sufficient",
      sufficiency_reason: "Most of the question is answered; one sub-part is not.",
    });

    renderWithProviders(<EvidenceGapPanel projectId="project-1" query="q" />);

    expect(
      await screen.findByText("No specific gap was identified for this question."),
    ).toBeInTheDocument();
  });

  it("still offers the upload action when the project has no asset to analyze", async () => {
    vi.mocked(assetsService.listAssets).mockResolvedValue([]);

    renderWithProviders(<EvidenceGapPanel projectId="project-1" query="q" />);

    await waitFor(() => expect(assetsService.listAssets).toHaveBeenCalledWith("project-1"));
    expect(researchService.analyzeResearchDocument).not.toHaveBeenCalled();
    expect(await screen.findByText(/drag/i)).toBeInTheDocument();
  });
});
