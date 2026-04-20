import { useEffect, useMemo, useRef, useState } from "react";

export interface CommandPaletteItem {
  id: string;
  label: string;
  subtitle?: string;
  keywords?: string[];
  disabled?: boolean;
  onSelect: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  items: CommandPaletteItem[];
  onClose: () => void;
}

function matches(item: CommandPaletteItem, query: string): boolean {
  if (!query) {
    return true;
  }
  const haystack = [item.label, item.subtitle || "", ...(item.keywords || [])].join(" ").toLowerCase();
  return haystack.includes(query.toLowerCase());
}

export function CommandPalette({ open, items, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const filteredItems = useMemo(() => items.filter((item) => matches(item, query)), [items, query]);

  useEffect(() => {
    if (!open) {
      return;
    }
    setQuery("");
    setActiveIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    if (activeIndex >= filteredItems.length) {
      setActiveIndex(filteredItems.length ? 0 : -1);
    }
  }, [activeIndex, filteredItems.length]);

  if (!open) {
    return null;
  }

  const activate = (index: number) => {
    const item = filteredItems[index];
    if (!item || item.disabled) {
      return;
    }
    item.onSelect();
    onClose();
  };

  return (
    <div className="dialogBackdrop" role="presentation" onClick={onClose}>
      <div className="commandPalette" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="commandPalette__header">
          <div>
            <h2>Jump to field</h2>
            <p>Search app fields, service descriptions, or workspace actions.</p>
          </div>
          <button className="ghostButton" type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <input
          ref={inputRef}
          className="commandPalette__input"
          placeholder="Search title, release notes, service:web:port:80..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((current) => (filteredItems.length ? (current + 1) % filteredItems.length : -1));
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((current) => (filteredItems.length ? (current - 1 + filteredItems.length) % filteredItems.length : -1));
            }
            if (event.key === "Enter") {
              event.preventDefault();
              activate(activeIndex);
            }
            if (event.key === "Escape") {
              event.preventDefault();
              onClose();
            }
          }}
        />

        <div className="commandPalette__list" role="listbox" aria-label="Workspace commands">
          {filteredItems.length ? (
            filteredItems.map((item, index) => (
              <button
                key={item.id}
                className={`commandPalette__item ${index === activeIndex ? "commandPalette__item--active" : ""}`}
                type="button"
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => activate(index)}
                disabled={item.disabled}
              >
                <div className="commandPalette__label">{item.label}</div>
                {item.subtitle ? <div className="commandPalette__subtitle">{item.subtitle}</div> : null}
              </button>
            ))
          ) : (
            <div className="commandPalette__empty">No matching fields or actions.</div>
          )}
        </div>
      </div>
    </div>
  );
}
