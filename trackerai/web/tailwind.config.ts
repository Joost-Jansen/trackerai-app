import type { Config } from "tailwindcss";
import preset from "@trackerai/ui/tailwind-preset";

// Only Tailwind's base layer is used (app/globals.css); the preset keeps its theme the same as the apps'.
const config: Config = {
  presets: [preset as Config],
  content: ["./app/**/*.{ts,tsx}"],
};

export default config;
