(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function Tabs({ value, onValueChange, items, className, ariaLabel = "Tabs" }) {
    return (
      <div className={cx("tabs", className)} role="tablist" aria-label={ariaLabel}>
        {items.map((item) => {
          const active = item.key === value;
          const disabled = Boolean(item.disabled);
          return (
            <button
              key={item.key}
              type="button"
              role="tab"
              className={cx("tab", { "tab--active": active })}
              aria-selected={active ? "true" : "false"}
              aria-current={active ? "page" : undefined}
              disabled={disabled}
              onClick={() => onValueChange?.(item.key)}
            >
              <span className="tab__label">{item.label}</span>
              {item.badge && <span className="tab__badge">{item.badge}</span>}
            </button>
          );
        })}
      </div>
    );
  }

  root.components.Tabs = Tabs;
})();

