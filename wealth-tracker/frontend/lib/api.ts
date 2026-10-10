// The shared fetch wrapper (@trackerai/ui/lib/api), with wealth-tracker's language header and example data.
//
// X-Locale tells the backend which language its error messages should be in.

import { ApiError, createApi, createExampleData } from "@trackerai/ui/lib/api";
import { locale } from "@/lib/i18n/locale";
import { tr } from "@/lib/i18n/tr";

export { ApiError };

// While the tour walks past the pages it shows a shared example account instead of an empty new one (backend:
// deps.example_mode). The backend decides which routes that applies to and refuses every write there.
const example = createExampleData();
export const setExampleData = example.set;
/** For components that read differently while example data is on (useExampleData). */
export const subscribeExampleData = example.subscribe;
export const isExampleData = example.isOn;

export const api = createApi({
  headers: (path) => ({ "X-Locale": locale, ...example.header(path) }),
  // Errors whose server message is not in the reader's language (they come from the shared security layer before
  // the app sets the language).
  message: (code) =>
    code === "csrf_origin" ? tr("This request did not come from this site and was refused. Reload the page and try again.") : null,
});
