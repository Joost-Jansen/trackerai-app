import type { Config } from "tailwindcss";
import preset from "@trackerai/ui/tailwind-preset";

// The theme is shared (packages/ui/tailwind-preset.ts); this app only says where its classes are.
const config: Config = {
  presets: [preset as Config],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}", "../../packages/ui/src/**/*.{ts,tsx}"],
};

export default config;
