(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function Toast({ title, message, variant = "info", exiting = false, onDismiss }) {
    return (
      <div
        className={cx("toast", `toast--${variant}`, !exiting && "toast-enter", exiting && "toast--exiting")}
        role="status"
        aria-live="polite"
      >
        <div className="toast__content">
          {title && <div className="toast__title">{title}</div>}
          {message && <div className="toast__message">{message}</div>}
        </div>
        {onDismiss && (
          <button className="toast__close" type="button" aria-label="Dismiss" onClick={onDismiss}>
            ×
          </button>
        )}
      </div>
    );
  }

  function ToastHost({ toasts, onDismiss }) {
    if (!toasts || toasts.length === 0) {
      return null;
    }
    return (
      <div className="toastHost" aria-label="Notifications">
        {toasts.map((toast) => (
          <Toast
            key={toast.id}
            title={toast.title}
            message={toast.message}
            variant={toast.variant}
            exiting={Boolean(toast.exiting)}
            onDismiss={() => onDismiss?.(toast.id)}
          />
        ))}
      </div>
    );
  }

  root.components.ToastHost = ToastHost;
})();

