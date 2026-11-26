import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const FRONTEND = process.cwd();
const GATE = readFileSync(join(FRONTEND, "..", "docs", "F0A_GATE.md"), "utf8");
const GATE_B = readFileSync(join(FRONTEND, "..", "docs", "F0B_GATE.md"), "utf8");
const GATE_F1 = readFileSync(join(FRONTEND, "..", "docs", "F1_GATE.md"), "utf8");
const WORKFLOW = readFileSync(join(FRONTEND, "..", ".github", "workflows", "frontend.yml"), "utf8");

function testTitles(): string {
  const dirs = [join(FRONTEND, "tests", "unit"), join(FRONTEND, "tests", "unit", "static"), join(FRONTEND, "tests", "e2e")];
  return dirs
    .flatMap((dir) => readdirSync(dir).filter((f) => /\.(test|spec)\.tsx?$/.test(f)).map((f) => readFileSync(join(dir, f), "utf8")))
    .join("\n");
}

describe("gate traceability", () => {
  it("every F0-A gate item has at least one test that names it", () => {
    const ids = [...GATE.matchAll(/^\| (GF0A-\d{2}) \|/gm)].map((m) => m[1]!);
    expect(ids.length).toBe(23);
    const titles = testTitles();
    const missing = ids.filter((id) => id !== "GF0A-23" && !new RegExp(`(it|test|describe)\\(\\s*"[^"]*${id}`).test(titles));
    expect(missing).toEqual([]);
  });

  it("GF0A-23 the frontend CI workflow runs every required check", () => {
    for (const step of ["npm ci", "npm run lint", "npm run typecheck", "npm test", "npm audit --audit-level=high", "npm run build", "npx playwright test", "git diff --exit-code -- lib/api/openapi.json lib/api/schema.d.ts", "cache-dependency-path: frontend/package-lock.json"]) {
      expect(WORKFLOW, step).toContain(step);
    }
  });

  it("every F0-B gate item has at least one test that names it", () => {
    const ids = [...GATE_B.matchAll(/^\| (GF0B-\d{2}) \|/gm)].map((m) => m[1]!);
    expect(ids.length).toBe(30);
    const titles = testTitles();
    const missing = ids.filter((id) => id !== "GF0B-30" && !new RegExp(`(it|test|describe)\\(\\s*"[^"]*${id}`).test(titles));
    expect(missing).toEqual([]);
  });

  it("GF0B-30 the frontend CI keeps every F0-A check and runs the real-backend E2E with the processing worker's needs", () => {
    for (const step of [
      "npm ci",
      "npm run lint",
      "npm run typecheck",
      "npm test",
      "npm audit --audit-level=high",
      "npm run build",
      "npx playwright test",
      "git diff --exit-code -- lib/api/openapi.json lib/api/schema.d.ts",
      "tesseract-ocr",
      "path: ~/.cache/huggingface",
    ]) {
      expect(WORKFLOW, step).toContain(step);
    }
    const backend = readFileSync(join(FRONTEND, "..", ".github", "workflows", "backend.yml"), "utf8");
    expect(backend).toContain("python -m unittest discover -s backend/tests -t .");
    expect(readFileSync(join(FRONTEND, "scripts", "e2e-backend.sh"), "utf8")).toContain('INTELLISTUDY_WORKER_ENABLED="${E2E_WORKER_ENABLED:-true}"');
  });

  it("every F1 gate item has at least one test that names it", () => {
    const ids = [...GATE_F1.matchAll(/^\| (GF1-\d{2}) \|/gm)].map((m) => m[1]!);
    expect(ids.length).toBe(27);
    const titles = testTitles();
    const missing = ids.filter((id) => id !== "GF1-27" && !new RegExp(`(it|test|describe)\\(\\s*"[^"]*${id}`).test(titles));
    expect(missing).toEqual([]);
  });

  it("GF1-27 the frontend CI keeps every check and runs the isolated E2E with the deterministic provider", () => {
    for (const step of ["npm ci", "npm run lint", "npm run typecheck", "npm test", "npm audit --audit-level=high", "npm run build", "npx playwright test", "git diff --exit-code -- lib/api/openapi.json lib/api/schema.d.ts", "tesseract-ocr", "INTELLISTUDY_E2E: \"1\"", "DETERMINISTIC TEST PROVIDER"]) {
      expect(WORKFLOW, step).toContain(step);
    }
    expect(WORKFLOW).not.toMatch(/DEEPSEEK_API_KEY|OPENAI_API_KEY|secrets\.(?!GITHUB_TOKEN)/);
  });
});
