import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/common/StatusBadge";

describe("StatusBadge", () => {
  it("renders the label lib/status resolves for the given domain and value", () => {
    render(<StatusBadge domain="grounding" value="grounded" />);
    expect(screen.getByText("Grounded")).toBeInTheDocument();
  });

  it("re-renders with the new outcome's text when the value changes (Sprint 9K.9 status-change motion)", async () => {
    const { rerender } = render(<StatusBadge domain="researchRun" value="running" />);
    expect(screen.getByText("In Progress")).toBeInTheDocument();

    rerender(<StatusBadge domain="grounding" value="grounded" />);
    // `mode="wait"` lets the outgoing value's exit animation finish
    // before the new one mounts — real and correct (it's what keeps two
    // outcomes from ever being on screen at once), but asynchronous, the
    // same as `TechnicalDetails`' own collapse.
    await waitFor(() => expect(screen.getByText("Grounded")).toBeInTheDocument());
    expect(screen.queryByText("In Progress")).not.toBeInTheDocument();
  });

  it("falls back to a neutral badge with the raw value for a status this domain doesn't recognise, rather than hiding it", () => {
    render(<StatusBadge domain="grounding" value="some_future_outcome" />);
    expect(screen.getByText("some_future_outcome")).toBeInTheDocument();
  });
});
