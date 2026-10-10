// Input fields. One layer of chrome around everything: label above, hint below,
// and the control itself without a border but with an inset box-shadow — that
// way a field's height stays exactly 36px, whether it draws a border or not.
//
// Focus is 1px ink plus a brand-coloured ring at 20%. That is the only moment
// the brand colour appears in a form.

import { useId } from "react";

function Field({
  label,
  hint,
  error,
  htmlFor,
  className = "",
  children,
}: {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  htmlFor?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`ds-field ${className}`}>
      {label && (
        <label className="ds-field__label" htmlFor={htmlFor}>
          {label}
        </label>
      )}
      {children}
      {(error || hint) && (
        <span className={`ds-field__hint ${error ? "ds-field__hint--error" : ""}`}>{error ?? hint}</span>
      )}
    </div>
  );
}

export function Input({
  label,
  hint,
  error,
  icon,
  size = "md",
  className = "",
  id,
  ...rest
}: {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  /** A glyph on the left *in* the field — a magnifying glass for a search field. */
  icon?: React.ReactNode;
  size?: "md" | "lg";
  className?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "size" | "className">) {
  const auto = useId();
  const fieldId = id ?? auto;
  const input = (
    <input
      id={fieldId}
      aria-invalid={error ? true : undefined}
      className={`ds-input ${size === "lg" ? "ds-input--lg" : ""} ${className}`}
      {...rest}
    />
  );
  return (
    <Field label={label} hint={hint} error={error} htmlFor={fieldId}>
      {icon ? (
        <span className="ds-input-wrap">
          <span className="ds-input-wrap__icon">{icon}</span>
          {input}
        </span>
      ) : (
        input
      )}
    </Field>
  );
}

export function Select({
  label,
  hint,
  error,
  className = "",
  id,
  children,
  ...rest
}: {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  className?: string;
} & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "className">) {
  const auto = useId();
  const fieldId = id ?? auto;
  return (
    <Field label={label} hint={hint} error={error} htmlFor={fieldId}>
      <select id={fieldId} className={`ds-select ${className}`} {...rest}>
        {children}
      </select>
    </Field>
  );
}

/**
 * A checkbox. The real <input> stays in the tree (hidden but reachable), so
 * keyboard, form state and screen readers work as they should; the square next
 * to it is purely the drawing.
 */
export function Checkbox({
  label,
  checked,
  onChange,
  disabled = false,
  className = "",
  ...rest
}: {
  label?: React.ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  className?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "checked" | "className" | "type">) {
  return (
    <label
      className={`ds-check ${checked ? "ds-check--on" : ""} ${disabled ? "ds-check--disabled" : ""} ${className}`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
        {...rest}
      />
      <span className="ds-check__box" aria-hidden>
        <svg className="ds-check__tick" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M2.5 6.2 4.8 8.5 9.5 3.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      {label && <span>{label}</span>}
    </label>
  );
}

/** A switch for something that takes effect at once. When it is on, it is green. */
export function Switch({
  label,
  checked,
  onChange,
  disabled = false,
  className = "",
  ...rest
}: {
  label?: React.ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  className?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "checked" | "className" | "type">) {
  return (
    <label
      className={`ds-switch ${checked ? "ds-switch--on" : ""} ${disabled ? "ds-switch--disabled" : ""} ${className}`}
    >
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
        {...rest}
      />
      <span className="ds-switch__track" aria-hidden>
        <span className="ds-switch__thumb" />
      </span>
      {label && <span>{label}</span>}
    </label>
  );
}
