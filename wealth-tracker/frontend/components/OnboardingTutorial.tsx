"use client";

// The DeGiro exports as a step-by-step plan: standalone (Help → Portfolio) and
// as a dialog behind "How do I export this?" in Update. The steps and images
// are in steps/degiro.tsx, the shape in steps/StepPlan.tsx — the same as every
// other step-by-step plan in the app, and as the tour.

import { StepPlan, StepPlanDialog } from "@/components/steps/StepPlan";
import { DEGIRO_ROUTES } from "@/components/steps/degiro";
import { tr } from "@/lib/i18n";

export function DegiroSteps({ onUpdate }: { onUpdate?: () => void }) {
  return (
    <StepPlan routes={DEGIRO_ROUTES} phone="mobile"
      done={onUpdate ? { label: tr("To Update"), onClick: onUpdate } : undefined} />
  );
}

export default function DegiroExplanation({ open, onClose, onUpdate }: {
  open: boolean;
  onClose: () => void;
  /** After the last step: the natural moment to open Update. */
  onUpdate?: () => void;
}) {
  return (
    <StepPlanDialog open={open} onClose={onClose} title={tr("Files from DeGiro")} routes={DEGIRO_ROUTES} phone="mobile"
      done={onUpdate ? { label: tr("To Update"), onClick: () => { onClose(); onUpdate(); } } : undefined} />
  );
}
