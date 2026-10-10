// A number that carries its own sign and is coloured by it.
//
// Since the Meridian redesign this is a thin shell around ds/ValueChange's
// `SignedValue`: *that* is where the colour and the real minus sign live, and it
// is more important that every amount in the app looks the same than that every
// page keeps its own variant. The props stayed what they were, so the existing
// calls could stay untouched when the colours changed.
//
// New code uses ds/ValueChange (with an arrow, for a movement) or SignedValue
// directly (without an arrow, for a sum that must add up).

import { SignedValue } from "@/components/ds";

export default function SignedAmount({
  value,
  decimals = 2,
  prefix = "",
  suffix = "",
  bold = false,
  className = "",
}: {
  value: number | null | undefined;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  bold?: boolean;
  className?: string;
}) {
  return (
    <SignedValue
      value={value}
      decimals={decimals}
      prefix={prefix}
      suffix={suffix}
      className={`${bold ? "font-medium" : ""} ${className}`.trim()}
    />
  );
}
