import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectHeader } from "@/features/projects/ProjectHeader";
import { aiProfile, makeAsset, makeProject } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";

vi.mock("@/services/projects");

describe("ProjectHeader — Start Research", () => {
  afterEach(() => vi.restoreAllMocks());

  it("warns and offers upload when the project has no documents", async () => {
    const onRequestUpload = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <ProjectHeader project={makeProject()} assets={[]} runs={[]} onRequestUpload={onRequestUpload} />,
    );
    await user.click(screen.getByRole("button", { name: /start research/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/upload documents first/i);
    await user.click(screen.getByRole("button", { name: "Upload documents" }));
    expect(onRequestUpload).toHaveBeenCalled();
  });

  it("warns when documents exist but none has finished processing", async () => {
    const user = userEvent.setup();
    const processing = makeAsset({
      ai_profile: aiProfile({ status: "completed", embedding_status: "processing" }),
    });

    renderWithProviders(
      <ProjectHeader project={makeProject()} assets={[processing]} runs={[]} onRequestUpload={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /start research/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/still processing/i);
  });

  it("starts research without a warning once a document is embedded", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <ProjectHeader project={makeProject()} assets={[makeAsset()]} runs={[]} onRequestUpload={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /start research/i }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
