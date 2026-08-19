import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UploadDropzone } from "@/features/assets/UploadDropzone";
import * as assetsService from "@/services/assets";
import { renderWithProviders } from "@/test/render";
import type { components } from "@/types/api";

vi.mock("@/services/assets");

type AssetRead = components["schemas"]["AssetRead"];

function makeAsset(): AssetRead {
  return {
    id: "asset-1",
    project_id: "project-1",
    owner_id: "owner-1",
    title: "doc",
    description: null,
    asset_type: "other",
    status: "active",
    mime_type: "text/plain",
    file_name: "abc_poultry.txt",
    file_extension: ".txt",
    file_size: 1024,
    checksum: "abc",
    source: "upload",
    version: 1,
    tags: [],
    metadata: {},
    ai_profile: {
      embedding_status: "pending",
      status: "pending",
    },
    created_by: null,
    processing_status: "queued",
    processing_error: null,
    processing_started_at: null,
    processing_completed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

describe("UploadDropzone", () => {
  afterEach(() => vi.restoreAllMocks());

  it("names the exact formats the backend can actually extract", () => {
    renderWithProviders(<UploadDropzone projectId="project-1" />);
    expect(screen.getByText(/Supported formats: \.txt, \.csv, \.md, \.json/)).toBeInTheDocument();
  });

  it("uploads the selected file and shows a loading state while it's in flight", async () => {
    let resolveUpload: (value: AssetRead) => void = () => {};
    vi.mocked(assetsService.uploadAsset).mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    const user = userEvent.setup();
    const file = new File(["ABC Poultry FY2026"], "abc_poultry.txt", { type: "text/plain" });

    renderWithProviders(<UploadDropzone projectId="project-1" />);
    const input = screen.getByLabelText("Upload research document").querySelector(
      "input[type=file]",
    ) as HTMLInputElement;
    await user.upload(input, file);

    expect(await screen.findByText("Uploading…")).toBeInTheDocument();
    expect(assetsService.uploadAsset).toHaveBeenCalledWith("project-1", file);

    resolveUpload(makeAsset());
    await waitFor(() => {
      expect(screen.queryByText("Uploading…")).not.toBeInTheDocument();
    });
  });

  it("shows a human-readable error when the upload fails", async () => {
    vi.mocked(assetsService.uploadAsset).mockRejectedValue({
      status: 422,
      message: "The file could not be processed.",
    });
    const user = userEvent.setup();
    const file = new File(["bad"], "bad.txt", { type: "text/plain" });

    renderWithProviders(<UploadDropzone projectId="project-1" />);
    const input = screen.getByLabelText("Upload research document").querySelector(
      "input[type=file]",
    ) as HTMLInputElement;
    await user.upload(input, file);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The file could not be processed.",
    );
  });
});
