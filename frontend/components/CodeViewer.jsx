(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function CodeViewer({ value, placeholder, className, maxHeight = 420 }) {
    const text = String(value ?? "");
    const shown = text.trim() ? text : placeholder || "";
    return (
      <pre className={cx("code", className)} style={{ maxHeight }}>
        <code>{shown}</code>
      </pre>
    );
  }

  root.components.CodeViewer = CodeViewer;
})();

