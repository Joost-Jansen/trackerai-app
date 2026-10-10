// The shared date ticks (@trackerai/ui/lib/dateTicks) in this page load's language.

import { dateTicks as ticks, tickFractions as fractions } from "@trackerai/ui/lib/dateTicks";
import { locale } from "@/lib/i18n";

export const dateTicks = (first: string, last: string, width: number) => ticks(first, last, width, locale);
export const tickFractions = (days: string[], width: number) => fractions(days, width, locale);
