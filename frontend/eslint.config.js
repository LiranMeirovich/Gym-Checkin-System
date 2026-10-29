// ESLint: lint rules only. Formatting is Prettier's job, so
// eslint-config-prettier switches off every rule that would fight it.
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src/*/api/schema.d.ts"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.strict,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: { globals: globals.browser },
  },
  {
    // The public build is reachable from the internet and must never
    // contain admin screens or admin API calls (decision 0020). Shown in
    // the editor here; vite.config.ts fails the public build as well.
    files: ["src/public/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/admin", "**/admin/**"],
              message: "The public app must not import admin code.",
            },
          ],
        },
      ],
    },
  },
  {
    // Admin and public share code only through src/shared.
    files: ["src/admin/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/public", "**/public/**"],
              message: "Move shared code to src/shared instead.",
            },
          ],
        },
      ],
    },
  },
  prettier,
);
