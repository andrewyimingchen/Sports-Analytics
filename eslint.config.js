// ESLint for the PWA (src/nba_insights/api/static) and its unit tests.
// The mobile app has its own config under mobile/.
import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: ["mobile/**", "node_modules/**", "src/nba_insights/api/static/vendor/**", ".venv/**"],
  },
  js.configs.recommended,
  {
    files: ["src/nba_insights/api/static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    rules: {
      "no-unused-vars": ["error", { args: "after-used", argsIgnorePattern: "^_" }],
      "no-implicit-globals": "error",
      eqeqeq: ["error", "smart"],
    },
  },
  {
    // The service worker is a classic script with worker globals.
    files: ["src/nba_insights/api/static/sw.js"],
    languageOptions: { sourceType: "script", globals: { ...globals.serviceworker } },
  },
  {
    files: ["tests/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.node },
    },
  },
];
