import { PropsWithChildren, useEffect, useState } from "react";

interface AccordionProps extends PropsWithChildren {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function Accordion({ title, subtitle, defaultOpen = true, open: controlledOpen, onOpenChange, children }: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (typeof controlledOpen === "boolean") {
      setOpen(controlledOpen);
    }
  }, [controlledOpen]);

  const toggle = () => {
    const next = !open;
    if (typeof controlledOpen !== "boolean") {
      setOpen(next);
    }
    onOpenChange?.(next);
  };

  return (
    <section className={`panel ${open ? "panel--open" : ""}`}>
      <button className="panel__header" type="button" onClick={toggle}>
        <div>
          <div className="panel__title">{title}</div>
          {subtitle ? <div className="panel__subtitle">{subtitle}</div> : null}
        </div>
        <span className="panel__chevron">{open ? "-" : "+"}</span>
      </button>
      {open ? <div className="panel__body">{children}</div> : null}
    </section>
  );
}
