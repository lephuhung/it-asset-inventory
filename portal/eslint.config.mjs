import next from "eslint-config-next";

/**
 * Flat config (ESLint ≥9, Next 16). `eslint-config-next` v16 export sẵn mảng
 * flat config gồm @next/eslint-plugin-next + react + react-hooks v7 + jsx-a11y
 * + typescript-eslint. Chạy: `pnpm lint` (eslint .)
 */
const eslintConfig = [
  ...next,
  {
    rules: {
      // Nhóm rule "React Compiler era" của react-hooks v7: đúng về nguyên tắc
      // nhưng bắn vào idiom fetch-on-mount / memo thủ công hiện có của toàn
      // codebase (~100 điểm). Hạ xuống warn — sẽ siết lại khi refactor data
      // layer (useApiQuery). Rule đúng-sai cứng (exhaustive-deps,
      // rules-of-hooks) giữ nguyên error.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/gating": "warn",
      "react-hooks/incompatible-library": "warn",
    },
  },
  {
    ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts"],
  },
];

export default eslintConfig;
