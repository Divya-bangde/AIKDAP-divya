import type { components } from "@/types/api";

type AIProfile = components["schemas"]["AIProfile"];

/** A complete `AIProfile` carrying the backend's own defaults, so a
 * fixture spells out only the fields its test is about -- and a new
 * backend field lands here once, not in every test that builds an asset. */
export function aiProfile(overrides: Partial<AIProfile> = {}): AIProfile {
  return {
    status: "pending",
    embedding_status: "pending",
    truncated: false,
    processed_sections: 0,
    total_sections: 0,
    ...overrides,
  };
}
