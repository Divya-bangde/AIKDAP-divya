import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TechnicalDetails } from "@/components/common/TechnicalDetails";

describe("TechnicalDetails", () => {
  it("is collapsed by default, with aria-expanded reflecting that", () => {
    render(
      <TechnicalDetails id="row-1">
        <p>Provider: gemini</p>
      </TechnicalDetails>,
    );

    const toggle = screen.getByRole("button", { name: "Technical details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Provider: gemini")).not.toBeInTheDocument();
  });

  it("reveals its content on click and hides it again on a second click", async () => {
    const user = userEvent.setup();
    render(
      <TechnicalDetails id="row-1">
        <p>Provider: gemini</p>
      </TechnicalDetails>,
    );

    const toggle = screen.getByRole("button", { name: "Technical details" });
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Provider: gemini")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(screen.queryByText("Provider: gemini")).not.toBeInTheDocument());
  });

  it("is operable from the keyboard with both Enter and Space", async () => {
    const user = userEvent.setup();
    render(
      <TechnicalDetails id="row-1">
        <p>Provider: gemini</p>
      </TechnicalDetails>,
    );

    const toggle = screen.getByRole("button", { name: "Technical details" });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps a stable accessible name rather than flipping between show/hide text", async () => {
    const user = userEvent.setup();
    render(
      <TechnicalDetails id="row-1">
        <p>Provider: gemini</p>
      </TechnicalDetails>,
    );

    const toggle = screen.getByRole("button", { name: "Technical details" });
    await user.click(toggle);
    // Still findable by the exact same accessible name after opening —
    // `aria-expanded` carries the state, not the label.
    expect(screen.getByRole("button", { name: "Technical details" })).toBe(toggle);
  });

  it("points aria-controls at a real, unique element id that exists once expanded", async () => {
    const user = userEvent.setup();
    render(
      <>
        <TechnicalDetails id="row-1">
          <p>First</p>
        </TechnicalDetails>
        <TechnicalDetails id="row-2">
          <p>Second</p>
        </TechnicalDetails>
      </>,
    );

    const [first, second] = screen.getAllByRole("button", { name: "Technical details" });
    const firstControls = first.getAttribute("aria-controls");
    const secondControls = second.getAttribute("aria-controls");

    expect(firstControls).toBeTruthy();
    expect(secondControls).toBeTruthy();
    expect(firstControls).not.toBe(secondControls);

    await user.click(first);
    expect(document.getElementById(firstControls!)).not.toBeNull();
    expect(document.getElementById(firstControls!)).toHaveTextContent("First");
  });

  it("contains no nested interactive control inside the toggle button", () => {
    render(
      <TechnicalDetails id="row-1">
        <p>Provider: gemini</p>
      </TechnicalDetails>,
    );

    const toggle = screen.getByRole("button", { name: "Technical details" });
    expect(toggle.querySelector("button, a, input, select, textarea")).toBeNull();
  });
});
