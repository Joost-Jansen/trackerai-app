module.exports = {
  plugins: {
    // Inlines the @imports of app/globals.css (the shared styles in @trackerai/ui) before Tailwind runs.
    "postcss-import": {},
    tailwindcss: {},
    autoprefixer: {},
  },
};
