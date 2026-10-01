"use client";

import { useId, type ReactNode } from "react";

/** Roving tab focus keeps keyboard navigation aligned with the visible panel. */
export default function SectionTabs<T extends string>({ items, value, onChange, children, label }: {
  items: readonly { id: T; label: string; compactLabel?: string }[]; value: T; onChange: (value: T) => void;
  children: ReactNode; label: string;
}) {
  const id = useId();
  return <div className="section-tabs">
    <div className="section-tab-list" role="tablist" aria-label={label}>
      {items.map((item, index) => <button type="button" key={item.id} role="tab" aria-label={item.label} id={`${id}-${item.id}`} aria-selected={value === item.id} aria-controls={`${id}-panel`} tabIndex={value === item.id ? 0 : -1}
        onClick={() => onChange(item.id)} onKeyDown={event => {
          let next = index;
          if (event.key === "ArrowRight") next = (index + 1) % items.length;
          else if (event.key === "ArrowLeft") next = (index + items.length - 1) % items.length;
          else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = items.length - 1;
          else return;
          event.preventDefault(); onChange(items[next].id);
          document.getElementById(`${id}-${items[next].id}`)?.focus();
        }}><span className="tab-label-desktop" aria-hidden="true">{item.label}</span><span className="tab-label-mobile" aria-hidden="true">{item.compactLabel ?? item.label}</span></button>)}
    </div>
    <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${value}`} tabIndex={0}>{children}</div>
  </div>;
}
