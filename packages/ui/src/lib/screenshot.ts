// A picture of what is on screen right now, for a feedback report: the visible part of the page, rendered in the
// browser (html-to-image), without the feedback dialog itself. No permission prompt, nothing leaves the browser until
// the user sends the report, and they see the picture first and can remove it.

const MAX_SIDE = 1600;
const TIMEOUT_MS = 8000;

/** SVG shapes styled from CSS (fill: none on a chart line) come out as black fills unless the style is inline. */
function pinSvgStyles(): () => void {
  const undo: (() => void)[] = [];
  document.querySelectorAll<SVGElement>("svg path, svg line, svg polyline, svg polygon, svg rect, svg circle, svg ellipse, svg text").forEach((el) => {
    const cs = getComputedStyle(el);
    const before = { fill: el.style.fill, stroke: el.style.stroke, strokeWidth: el.style.strokeWidth, opacity: el.style.opacity };
    el.style.fill = cs.fill;
    el.style.stroke = cs.stroke;
    el.style.strokeWidth = cs.strokeWidth;
    el.style.opacity = cs.opacity;
    undo.push(() => Object.assign(el.style, before));
  });
  return () => undo.forEach((f) => f());
}

export async function captureViewport(): Promise<string | null> {
  const restore = pinSvgStyles();
  try {
    const { toJpeg } = await import("html-to-image");
    const w = window.innerWidth;
    const h = window.innerHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, MAX_SIDE / Math.max(w, h));
    const picture = toJpeg(document.body, {
      quality: 0.8,
      pixelRatio: ratio,
      width: w,
      height: h,
      backgroundColor: getComputedStyle(document.body).backgroundColor,
      style: { transform: `translate(${-window.scrollX}px, ${-window.scrollY}px)`, transformOrigin: "top left" },
      imagePlaceholder: "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
      // Not the dialog, and not map tiles: those are other sites' images, and one that cannot be fetched again
      // spoils the whole picture. The route on the map stays.
      filter: (node) => !(node instanceof HTMLElement && (node.classList.contains("ds-scrim") || node.classList.contains("leaflet-tile"))),
    });
    // A slow page goes without a picture rather than keeping the dialog waiting.
    return await Promise.race([picture, new Promise<null>((resolve) => setTimeout(() => resolve(null), TIMEOUT_MS))]);
  } catch (err) {
    console.warn("screenshot failed", err);
    return null; // a page that cannot be drawn (a cross-origin map tile, say) just goes without a picture
  } finally {
    restore();
  }
}
