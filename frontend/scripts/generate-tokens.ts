// Writes design-system/tokens/tokens.css from design-system/tokens/tokens.ts. Run: npm run tokens (Node 24 strips types).
import { writeFileSync } from "node:fs";
import { buildTokenCss } from "../design-system/tokens/build-css.ts";

writeFileSync(new URL("../design-system/tokens/tokens.css", import.meta.url), buildTokenCss());
console.log("design-system/tokens/tokens.css written");
