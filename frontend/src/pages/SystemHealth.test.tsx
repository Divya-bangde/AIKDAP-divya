import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SystemHealth } from "@/pages/SystemHealth";
import * as healthService from "@/services/health";
import { renderWithProviders } from "@/test/render";

vi.mock("@/services/health");

describe("SystemHealth page", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the real component statuses returned by GET /health", async () => {
    vi.mocked(healthService.getHealth).mockResolvedValue({
      status: "degraded",
      app: "AIKDAP",
      version: "1.0.0",
      environment: "development",
      services: {
        postgres: { status: "healthy" },
        redis: { status: "healthy" },
        worker: { status: "healthy" },
        reranker: { status: "healthy" },
        gemini: { status: "quota_exhausted", detail: "Daily quota exhausted." },
        groq: { status: "configured" },
        openrouter: { status: "healthy" },
      },
    });

    renderWithProviders(<SystemHealth />);

    expect(await screen.findByText("Quota Exhausted")).toBeInTheDocument();
    expect(screen.getByText("Daily quota exhausted.")).toBeInTheDocument();
    // Overall status is rendered verbatim from the backend, not
    // recomputed from the individual components.
    expect(screen.getAllByText("degraded").length).toBeGreaterThan(0);
  });

  it("shows a real error state, not fake indicators, when health is unreachable", async () => {
    vi.mocked(healthService.getHealth).mockRejectedValue({
      status: 0,
      message: "Could not reach the server. Check your connection.",
    });

    renderWithProviders(<SystemHealth />);

    expect(await screen.findByText("Unable to retrieve system health.")).toBeInTheDocument();
  });
});
