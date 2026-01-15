(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function Spinner({ className }) {
    return <span className={cx("spinner", className)} aria-hidden="true" />;
  }

  function Button({
    variant = "primary",
    size = "md",
    loading = false,
    className,
    children,
    disabled,
    type = "button",
    ...props
  }) {
    const isDisabled = Boolean(disabled || loading);
    return (
      <button
        type={type}
        className={cx("btn", `btn--${variant}`, `btn--${size}`, className)}
        disabled={isDisabled}
        aria-disabled={isDisabled}
        aria-busy={loading ? "true" : "false"}
        {...props}
      >
        {loading && <Spinner />}
        <span className="btn__label">{children}</span>
      </button>
    );
  }

  function IconButton({
    label,
    variant = "ghost",
    size = "md",
    loading = false,
    className,
    children,
    disabled,
    type = "button",
    ...props
  }) {
    const isDisabled = Boolean(disabled || loading);
    return (
      <button
        type={type}
        className={cx("icon-btn", `icon-btn--${variant}`, `icon-btn--${size}`, className)}
        disabled={isDisabled}
        aria-label={label}
        title={label}
        aria-disabled={isDisabled}
        aria-busy={loading ? "true" : "false"}
        {...props}
      >
        {loading ? <Spinner /> : children}
      </button>
    );
  }

  root.components.Button = Button;
  root.components.IconButton = IconButton;
})();

