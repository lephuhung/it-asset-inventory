import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Portal standalone Compose startup", () => {
  it("copies Next static chunks into the standalone output", () => {
    const compose = readFileSync(resolve(process.cwd(), "..", "docker-compose.yml"), "utf8");

    expect(compose).toContain("cp -R .next/static .next/standalone/.next/static");
  });
});
