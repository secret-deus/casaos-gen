(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function Label({ htmlFor, children, className }) {
    return (
      <label className={cx("label", className)} htmlFor={htmlFor}>
        {children}
      </label>
    );
  }

  function Hint({ children, className }) {
    if (!children) {
      return null;
    }
    return <p className={cx("hint", className)}>{children}</p>;
  }

  function ErrorText({ children, className }) {
    if (!children) {
      return null;
    }
    return <p className={cx("error", className)}>{children}</p>;
  }

  function Field({ id, label, hint, error, className, children }) {
    return (
      <div className={cx("field", className)}>
        {label && <Label htmlFor={id}>{label}</Label>}
        {children}
        <ErrorText>{error}</ErrorText>
        <Hint>{hint}</Hint>
      </div>
    );
  }

  function Input({ id, className, ...props }) {
    return <input id={id} className={cx("input", className)} {...props} />;
  }

  function Textarea({ id, className, ...props }) {
    return <textarea id={id} className={cx("textarea", className)} {...props} />;
  }

  function Select({ id, className, children, ...props }) {
    return (
      <select id={id} className={cx("select", className)} {...props}>
        {children}
      </select>
    );
  }

  function Checkbox({ id, checked, onChange, label, hint, className, disabled }) {
    return (
      <label className={cx("checkbox", className, { "checkbox--disabled": disabled })} htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={Boolean(checked)}
          disabled={disabled}
          onChange={(event) => onChange?.(event.target.checked)}
        />
        <span className="checkbox__text">
          <span className="checkbox__label">{label}</span>
          {hint && <span className="checkbox__hint">{hint}</span>}
        </span>
      </label>
    );
  }

  root.components.Field = Field;
  root.components.Label = Label;
  root.components.Input = Input;
  root.components.Textarea = Textarea;
  root.components.Select = Select;
  root.components.Checkbox = Checkbox;
})();

