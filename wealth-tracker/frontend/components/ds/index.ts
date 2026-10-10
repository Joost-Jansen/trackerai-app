// Meridian's primitives. One entry point, so a page does not need to know six
// paths and a second version of the same button never arises.
//
// The shared ones live in packages/ui (@trackerai/ui/ds/*); this file adds the app's own. The class names come from app/ds.css, which comes verbatim from the handoff
// package. Whoever adds something here: design it against that package's rules
// instead of importing a library's version.

export { Button, ButtonLink, IconButton } from "@trackerai/ui/ds/Button";
export { Input, Select, Checkbox, Switch } from "@trackerai/ui/ds/Field";
export { default as Section, Eyebrow, Hero, Figure, Rule } from "@trackerai/ui/ds/Section";
export { default as ValueChange, SignedValue } from "./ValueChange";
export { default as Tabs, type TabItem } from "@trackerai/ui/ds/Tabs";
export { default as AllocationBar, type AllocationSegment } from "./AllocationBar";
export { Dialog, EmptyState, Tag, Badge } from "@trackerai/ui/ds/Feedback";
export { default as Logomark } from "./Logomark";
export { default as Explained } from "./Explained";
