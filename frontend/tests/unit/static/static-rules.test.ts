import { describe, expect, it } from "vitest";
import { sourceFiles } from "./scan";

describe("static rules over frontend source", () => {
  it("GF0A-02 no raw hex colour literal outside the generated token stylesheet", () => {
    const offenders = sourceFiles()
      .filter((f) => /#[0-9a-fA-F]{3,8}\b/.test(f.text.replace(/&#\d+;/g, "")))
      .map((f) => f.path);
    expect(offenders).toEqual([]);
  });

  it("GF0A-03 F-M4-03 — Frontend Rendering Safety: dangerouslySetInnerHTML is never used", () => {
    expect(sourceFiles().filter((f) => f.text.includes("dangerouslySetInnerHTML")).map((f) => f.path)).toEqual([]);
  });

  it("GF0A-07 no source file touches localStorage or sessionStorage", () => {
    expect(sourceFiles().filter((f) => /\b(localStorage|sessionStorage)\b/.test(f.text)).map((f) => f.path)).toEqual([]);
  });

  it("GF0A-07 tokens never travel in URLs: no access_token in query strings or route params", () => {
    const offenders = sourceFiles().filter((f) => /[?&](access_?token|token)=/.test(f.text)).map((f) => f.path);
    expect(offenders).toEqual([]);
  });
});
