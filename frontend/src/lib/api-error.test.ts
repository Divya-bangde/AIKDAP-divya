import { describe, expect, it } from "vitest";

import { messageFor, parseApiError } from "@/lib/api-error";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status });
}

describe("parseApiError", () => {
  it("extracts the message from a simple {detail: string} body", async () => {
    const error = await parseApiError(jsonResponse(404, { detail: "Project not found." }));
    expect(error).toEqual({ status: 404, message: "Project not found." });
  });

  it("extracts the first message from a FastAPI validation-error body", async () => {
    const error = await parseApiError(
      jsonResponse(422, {
        detail: [
          { loc: ["body", "email"], msg: "value is not a valid email address", type: "value_error" },
        ],
      }),
    );
    expect(error.status).toBe(422);
    expect(error.code).toBe("validation_error");
    expect(error.message).toBe("value is not a valid email address");
    expect(error.details).toEqual(["value is not a valid email address"]);
  });

  it("never throws on an unparseable body, and returns a generic safe message", async () => {
    const response = new Response("<html>not json</html>", { status: 500 });
    const error = await parseApiError(response);
    expect(error.status).toBe(500);
    expect(error.message).not.toContain("<html>");
  });

  it("never leaks a stack trace or internal detail through the generic message", async () => {
    const error = await parseApiError(jsonResponse(500, { unexpected: "shape" }));
    expect(error.message).not.toMatch(/traceback|exception|sql/i);
  });
});

describe("messageFor", () => {
  it("returns an ApiError's own message", () => {
    expect(messageFor({ status: 401, message: "Your session has expired." })).toBe(
      "Your session has expired.",
    );
  });

  it("returns a network-specific message for a fetch TypeError", () => {
    expect(messageFor(new TypeError("Failed to fetch"))).toMatch(/reach the server/i);
  });

  it("falls back to a generic message for anything else", () => {
    expect(messageFor("something weird")).toBe("An unexpected error occurred.");
  });
});
