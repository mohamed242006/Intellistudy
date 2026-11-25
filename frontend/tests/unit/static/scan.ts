import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export const ROOT = process.cwd(); // vitest runs from frontend/
const SOURCE_DIRS = ["app", "design-system", "features", "lib"];

/** Every frontend source file (TS, TSX, CSS), excluding generated API types and token output. */
export function sourceFiles(extra: { includeTokens?: boolean } = {}): { path: string; text: string }[] {
  const out: { path: string; text: string }[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.(tsx?|css)$/.test(entry)) out.push({ path: relative(ROOT, full), text: readFileSync(full, "utf8") });
    }
  };
  for (const dir of SOURCE_DIRS) walk(join(ROOT, dir));
  return out.filter((f) => !f.path.endsWith("schema.d.ts") && (extra.includeTokens || !f.path.startsWith("design-system/tokens/")));
}
