import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Production standalone: `.next/standalone/server.js` KHÔNG kèm static chunks —
 * nếu không COPY `.next/static` vào đúng vị trí thì mọi CSS/JS chunk 404 khi
 * chạy image production. (Dev compose đã chuyển sang Dockerfile.dev + dev
 * server, không còn dòng `cp -R` như trước — invariant chuyển sang Dockerfile.)
 */
describe("Portal standalone production image", () => {
  it("copies Next static chunks into the standalone output", () => {
    const dockerfile = readFileSync(resolve(process.cwd(), "Dockerfile"), "utf8");

    expect(dockerfile).toContain("/app/.next/standalone ./");
    expect(dockerfile).toContain("/app/.next/static ./.next/static");
    expect(dockerfile).toContain('"node", "server.js"');
  });
});
