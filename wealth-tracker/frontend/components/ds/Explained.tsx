"use client";

// A word with its explanation on hover (and on focus, for the keyboard): a dotted
// underline says there is more, the explanation appears in a small box below it.
// Used for column headers and card labels whose meaning isn't obvious from the
// word alone.

export default function Explained({ children, text, align = "left" }: {
  children: React.ReactNode;
  text: string;
  /** Which edge of the word the box lines up with; "right" for right-aligned columns. */
  align?: "left" | "right";
}) {
  return (
    <span className="group relative inline-block cursor-help" tabIndex={0}>
      <span className="underline decoration-dotted underline-offset-4">{children}</span>
      <span
        role="tooltip"
        className={`pointer-events-none absolute top-full z-20 mt-1.5 hidden w-64 whitespace-normal rounded-md border px-3 py-2 text-left text-xs font-normal normal-case leading-relaxed tracking-normal shadow-sm group-hover:block group-focus:block ${align === "right" ? "right-0" : "left-0"}`}
        style={{ background: "var(--surface)", borderColor: "var(--rule)", color: "var(--ink)" }}
      >
        {text}
      </span>
    </span>
  );
}
