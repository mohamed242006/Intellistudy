import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildTokenCss } from "@/design-system/tokens/build-css";
import { hexOf, primitives, radii, semantic, shadows, textStyles } from "@/design-system/tokens/tokens";

const CONTEXT = readFileSync(join(process.cwd(), "..", "docs", "figma_ui_context.md"), "utf8");
const CSS = readFileSync(join(process.cwd(), "design-system", "tokens", "tokens.css"), "utf8");

describe("GF0A-01 design tokens equal the Figma values recorded in figma_ui_context.md", () => {
  it("GF0A-01 semantic Light and Dark tokens match UI §4.1.2 row by row", () => {
    const rows = [...CONTEXT.matchAll(/^\| color\/(\S+) \| \w+\/\d+ `(#[0-9A-F]{6})` \| \w+\/\d+ `(#[0-9A-F]{6})` \|$/gm)];
    expect(rows.length).toBe(Object.keys(semantic).length);
    for (const [, token, light, dark] of rows) {
      const refs = semantic[token as string];
      expect(refs, token).toBeDefined();
      expect([hexOf(refs![0]), hexOf(refs![1])], token).toEqual([light, dark]);
    }
  });

  it("GF0A-01 primitive ramps match UI §4.1.1", () => {
    for (const [ramp, steps] of Object.entries(primitives)) {
      const row = CONTEXT.match(new RegExp(`^\\| ${ramp} \\| (.+) \\|$`, "m"));
      expect(row, ramp).not.toBeNull();
      const recorded = Object.fromEntries([...row![1]!.matchAll(/(\d+) `(#[0-9A-F]{6})`/g)].map((m) => [m[1], m[2]]));
      expect(Object.fromEntries(Object.entries(steps).map(([k, v]) => [k, v]))).toEqual(recorded);
    }
  });

  it("GF0A-01 text styles, radii and shadows match UI §4.2 and §4.5", () => {
    for (const [name, style] of Object.entries(textStyles)) {
      const row = CONTEXT.match(new RegExp(`^\\| text/${name} \\| [A-Za-z ]+ (\\d{3}) \\| (\\d+) / (\\d+) \\| ([−+-]?[\\d.]+%|0) \\|`, "m"));
      expect(row, name).not.toBeNull();
      const pct = row![4] === "0" ? 0 : Number(row![4]!.replace("−", "-").replace("%", ""));
      expect([style.weight, style.size, style.lineHeight, style.letterSpacingPct], name).toEqual([Number(row![1]), Number(row![2]), Number(row![3]), pct]);
    }
    expect(CONTEXT).toContain(`Radius tokens: sm ${radii.sm}, md ${radii.md}, lg ${radii.lg}, xl ${radii.xl}, full ${radii.full}.`);
    for (const [name, css] of Object.entries(shadows)) expect(CONTEXT, name).toContain(`\`shadow/${name}\` = \`${css}\``);
  });

  it("GF0A-01 tokens.css is generated from tokens.ts without drift, and Dark tokens are present but not the default", () => {
    expect(CSS).toBe(buildTokenCss());
    expect(CSS).toContain(':root[data-theme="dark"]');
  });
});
