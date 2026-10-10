import type { MetadataRoute } from "next";
import { APP } from "@/lib/app";

// What iOS and Android read as soon as someone puts the site on their home screen.
//
// The name below it is `short_name` — keep it short, otherwise the phone
// shortens it itself. The same spelling as the wordmark in the sidebar.
//
// `display: standalone` opens the app without an address bar and tabs. The
// status bar at the top gets its colour from the themeColor in layout.tsx, so it
// follows light and dark by itself.
//
// The icons themselves are app/icon.png and app/apple-icon.png in the same
// folder; Next turns those into /icon.png and /apple-icon.png and adds the
// <link> lines itself. A public/ folder would not be copied along by the
// Dockerfile — this route belongs to the build and so does go along.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: APP.name,
    short_name: APP.name,
    description: APP.tagline,
    start_url: "/",
    display: "standalone",
    lang: "nl",
    // Paper and walnut: the screen the app shows while it starts.
    background_color: APP.paper.light,
    theme_color: APP.paper.light,
    icons: [
      { src: "/icon.png", sizes: "512x512", type: "image/png" },
      { src: "/apple-icon.png", sizes: "180x180", type: "image/png" },
    ],
  };
}
