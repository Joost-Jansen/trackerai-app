// ESLint for every TypeScript and JavaScript file in the workspace: the Next apps and packages/. Formatting
// is Prettier's job (eslint-config-prettier, last, turns off the rules that would fight it).
import js from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const NEXT_APPS = ["health-tracker/web", "wealth-tracker/frontend", "trackerai/web", "tabstealth/web"];

export default tseslint.config(
  {
    ignores: [
      "**/node_modules/**",
      "**/.next/**",
      "**/out/**",
      "**/build/**",
      "**/dist/**",
      "**/coverage/**",
      "**/.venv/**",
      "**/next-env.d.ts",
    ],
  },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      // A parameter documents a signature (the en and nl texts share theirs), and `{ key, ...rest }` drops a field.
      "@typescript-eslint/no-unused-vars": ["error", { args: "none", ignoreRestSiblings: true, varsIgnorePattern: "^_" }],
      // `on ? set.add(x) : set.delete(x)` as a statement is the house style for toggles.
      "@typescript-eslint/no-unused-expressions": ["error", { allowTernary: true }],
    },
  },
  {
    files: ["**/*.{ts,tsx,js,jsx,mjs,cjs}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // These four check code for the React Compiler, which the apps do not use; rules-of-hooks and
      // exhaustive-deps stay on.
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/refs": "off",
      "react-hooks/purity": "off",
      "react-hooks/preserve-manual-memoization": "off",
    },
  },
  {
    // Registered everywhere, so a disable comment for one of its rules resolves in any file.
    plugins: { "@next/next": nextPlugin },
    settings: { next: { rootDir: NEXT_APPS } },
  },
  {
    // packages/ui renders inside the same Next apps; packages/marketing does not depend on Next.
    files: [...NEXT_APPS, "packages/ui"].map((dir) => `${dir}/**/*.{ts,tsx,js,jsx,mjs}`),
    rules: { ...nextPlugin.configs.recommended.rules, ...nextPlugin.configs["core-web-vitals"].rules },
  },
  {
    // Node scripts and Next configs in CommonJS.
    files: ["**/*.cjs", "**/next.config.js"],
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  prettier,
);
