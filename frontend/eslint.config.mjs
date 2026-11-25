import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  { ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**", "lib/api/schema.d.ts", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // F-M4-03 — Frontend Rendering Safety: server and model text is rendered as React text, never as HTML.
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "F-M4-03: never render server or model text as HTML.",
        },
        {
          selector: "MemberExpression[property.name=/^(localStorage|sessionStorage)$/]",
          message: "Tokens and credentials must never touch web storage (GF0A-07).",
        },
      ],
      "no-restricted-globals": ["error", "localStorage", "sessionStorage"],
    },
  },
  {
    // Tests read web storage only to assert that it stays empty; the rendering-safety ban still applies.
    files: ["tests/**"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "F-M4-03: never render server or model text as HTML.",
        },
      ],
      "no-restricted-globals": "off",
    },
  },
];

export default config;
