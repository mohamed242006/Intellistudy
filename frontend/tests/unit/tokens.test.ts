import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildTokenCss } from "@/design-system/tokens/build-css";
import { hexOf, motion, primitives, radii, semantic, shadows, textStyles } from "@/design-system/tokens/tokens";

/** The design source since v2.0 (it supersedes docs/figma_ui_context.md §4). */
const SPEC = readFileSync(join(process.cwd(), "..", "docs", "DESIGN_SPEC_NEW.md"), "utf8");
const CSS = readFileSync(join(process.cwd(), "design-system", "tokens", "tokens.css"), "utf8");

/** The markdown section that starts at `heading` and ends at the next heading of any level. */
function section(heading: string): string {
  const start = SPEC.indexOf(heading);
  expect(start, heading).toBeGreaterThan(-1);
  const rest = SPEC.slice(start + heading.length);
  const end = rest.search(/^#{2,4} /m);
  return end === -1 ? rest : rest.slice(0, end);
}

/** token → [light, dark] from the §8.2 table, including the grouped success/warning/danger rows. */
function semanticTable(): Map<string, [string, string]> {
  const table = new Map<string, [string, string]>();
  for (const line of section("### 8.2 Semantic tokens").split("\n")) {
    const cells = line.split("|").map((c) => c.trim());
    if (cells.length < 6) continue;
    const [, , token, , light, dark] = cells as [string, string, string, string, string, string];
    const hexes = (cell: string) => [...cell.matchAll(/#[0-9A-F]{6}/g)].map((m) => m[0]);
    const single = token.match(/^`([a-z-]+\/[a-z-]+)`$/);
    if (single) {
      table.set(single[1]!, [hexes(light)[0]!, hexes(dark)[0]!]);
      continue;
    }
    const grouped = token.match(/^`(\w+)\/bg` · `border` · `fg` · `solid`$/);
    if (grouped) {
      const [l, d] = [hexes(light), hexes(dark)];
      ["bg", "border", "fg", "solid"].forEach((part, i) => table.set(`${grouped[1]}/${part}`, [l[i]!, d[i]!]));
    }
  }
  return table;
}

describe("GF0A-01 design tokens equal the Figma values recorded in docs/DESIGN_SPEC_NEW.md", () => {
  it("GF0A-01 semantic Light and Dark tokens match spec §8.2 row by row", () => {
    const table = semanticTable();
    expect(table.size).toBe(Object.keys(semantic).length);
    for (const [token, refs] of Object.entries(semantic)) {
      expect(table.get(token), token).toEqual([hexOf(refs[0]), hexOf(refs[1])]);
    }
  });

  it("GF0A-01 primitive ramps match spec §8.1", () => {
    const body = section("### 8.1 Primitive ramps");
    const header = body.split("\n").find((l) => l.startsWith("| Ramp"))!;
    const steps = header.split("|").map((c) => c.trim()).filter(Boolean).slice(1);
    for (const [ramp, values] of Object.entries(primitives)) {
      const row = body.split("\n").find((l) => l.startsWith(`| **${ramp}** |`));
      expect(row, ramp).toBeDefined();
      const cells = row!.split("|").map((c) => c.trim()).filter(Boolean).slice(1);
      const recorded = Object.fromEntries(steps.map((step, i) => [step, cells[i]]).filter(([, v]) => v && v !== "–"));
      expect({ ...values }, ramp).toEqual(recorded);
    }
  });

  it("GF0A-01 text styles (§7), radii (§9.2), shadows (§9.4) and motion (§9.8) match the spec", () => {
    const type = section("## 7. Typography System");
    for (const [name, style] of Object.entries(textStyles)) {
      const row = type.match(new RegExp(`^\\| \`text/${name}\` \\| \`[^\`]+\` \\| \\*\\*(\\d+)\\*\\* \\| \\*\\*(\\d+)\\*\\* \\| [A-Za-z ]+ (\\d{3}) \\| ([−-]?[\\d.]+)`, "m"));
      expect(row, name).not.toBeNull();
      const pct = Number(row![4]!.replace("−", "-"));
      expect([style.size, style.lineHeight, style.weight, style.letterSpacingPct], name).toEqual([Number(row![1]), Number(row![2]), Number(row![3]), pct]);
    }
    const radius = section("### 9.2 Radius");
    for (const [name, px] of Object.entries(radii)) expect(radius, name).toMatch(new RegExp(`^\\| \`radius/${name}\` \\| ${px} \\|`, "m"));
    const shadow = section("### 9.4 Shadows");
    for (const [name, css] of Object.entries(shadows)) {
      const row = shadow.match(new RegExp(`^\\| \`shadow/${name}\` \\| (.+) \\|$`, "m"));
      expect(row, name).not.toBeNull();
      const recorded = [...row![1]!.matchAll(/0 (\d+)px (\d+)px 0 \*\*#0D1217([0-9A-F]{2})\*\*/g)].map(
        (m) => `0 ${m[1]}px ${m[2]}px rgb(13 18 23 / ${Math.round((parseInt(m[3]!, 16) / 255) * 100)}%)`,
      );
      expect(css.split(", "), name).toEqual(recorded);
    }
    const motionTable = section("### 9.8 Motion tokens");
    expect(motionTable).toContain(`| \`motion/fast\` | ${motion.fast} ms |`);
    expect(motionTable).toContain(`| \`motion/base\` | ${motion.base} ms |`);
    expect(motionTable).toContain(`| \`motion/slow\` | ${motion.slow} ms |`);
    expect(motionTable).toContain(`| \`easing/standard\` | ${motion.easeStandard} |`);
    expect(motionTable).toContain(`| \`easing/exit\` | ${motion.easeExit} |`);
  });

  it("GF0A-01 tokens.css is generated from tokens.ts without drift, and Dark tokens are present but not the default", () => {
    expect(CSS).toBe(buildTokenCss());
    expect(CSS).toContain(':root[data-theme="dark"]');
    expect(CSS).toContain("--is-accent-default: #2F5D46;");
  });
});
