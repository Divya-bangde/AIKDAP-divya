import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SRC_ROOT = path.resolve(__dirname, "..");

/** Mirrors the backend's `test_litellm_is_imported_only_by_the_gateway`
 * pattern (Sprint 9A/9J): the architectural claim in `client.ts`'s
 * docstring — "the ONLY module that calls fetch()" — must actually
 * hold, not just be a comment nobody enforces. */
function collectTsxFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  const files: string[] = [];
  for (const entry of entries) {
    if (entry === "node_modules" || entry === "types") continue;
    const fullPath = path.join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      files.push(...collectTsxFiles(fullPath));
    } else if (/\.(ts|tsx)$/.test(entry) && !entry.endsWith(".test.ts") && !entry.endsWith(".test.tsx")) {
      files.push(fullPath);
    }
  }
  return files;
}

describe("fetch() containment (Phase 5)", () => {
  it("is called nowhere outside services/client.ts", () => {
    const offenders: string[] = [];
    for (const file of collectTsxFiles(SRC_ROOT)) {
      if (file.endsWith(path.join("services", "client.ts"))) continue;
      const content = readFileSync(file, "utf-8");
      if (/\bfetch\(/.test(content)) {
        offenders.push(path.relative(SRC_ROOT, file));
      }
    }
    expect(offenders).toEqual([]);
  });
});
