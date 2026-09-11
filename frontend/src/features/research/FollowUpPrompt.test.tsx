import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FollowUpPrompt } from "@/features/research/FollowUpPrompt";
import * as researchService from "@/services/research";
import { renderWithProviders } from "@/test/render";

vi.mock("@/services/research");

describe("FollowUpPrompt", () => {
  afterEach(() => vi.restoreAllMocks());

  it("starts a new run linked to its parent", async () => {
    const start = vi.mocked(researchService.startResearchRun);
    start.mockResolvedValue({ run_id: "run-2" } as Awaited<ReturnType<typeof start>>);

    renderWithProviders(<FollowUpPrompt runId="run-1" projectId="project-1" />);

    const ask = screen.getByRole("button", { name: /ask/i });
    // Under the API's 3-character minimum, so nothing can be sent yet.
    expect(ask).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Ask a follow-up"), {
      target: { value: "Explain that briefly" },
    });
    fireEvent.click(ask);

    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        project_id: "project-1",
        parent_run_id: "run-1",
        query: "Explain that briefly",
      }),
    );
  });
});
