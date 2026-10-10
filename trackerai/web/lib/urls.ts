/** Where each tracker lives (LANDING_HEALTH_URL, LANDING_WEALTH_URL), read per request; a tracker without one is not
 *  offered. */
export function trackerUrls(): { health?: string; wealth?: string } {
  const clean = (v: string | undefined) => v?.trim().replace(/\/+$/, "") || undefined;
  return { health: clean(process.env.LANDING_HEALTH_URL), wealth: clean(process.env.LANDING_WEALTH_URL) };
}
