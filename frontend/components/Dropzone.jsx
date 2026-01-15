(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));
  const formatBytes = root.utils?.formatBytes || ((value) => `${value} B`);

  function Dropzone({
    id,
    file,
    accept = ".yml,.yaml",
    disabled = false,
    title = "Drop file here",
    description = "Drag & drop a docker-compose YAML, or click to browse.",
    onFileChange,
    className,
  }) {
    const inputId = id || "dropzone-file";
    const [dragOver, setDragOver] = React.useState(false);

    const handleFiles = (files) => {
      const next = files?.[0];
      if (!next) {
        return;
      }
      onFileChange?.(next);
    };

    return (
      <div
        className={cx("dropzone", className, {
          "dropzone--active": dragOver,
          "dropzone--disabled": disabled,
        })}
        onDragEnter={(event) => {
          event.preventDefault();
          if (disabled) return;
          setDragOver(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (disabled) return;
          setDragOver(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setDragOver(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          if (disabled) return;
          setDragOver(false);
          handleFiles(event.dataTransfer.files);
        }}
      >
        <input
          id={inputId}
          type="file"
          accept={accept}
          disabled={disabled}
          className="dropzone__input"
          onChange={(event) => handleFiles(event.target.files)}
        />
        <label htmlFor={inputId} className="dropzone__label">
          <div className="dropzone__title">{title}</div>
          <div className="dropzone__desc">{description}</div>
          {file ? (
            <div className="dropzone__file">
              <div className="dropzone__fileName">{file.name}</div>
              <div className="dropzone__fileMeta">{formatBytes(file.size)}</div>
            </div>
          ) : (
            <div className="dropzone__hint">{accept}</div>
          )}
        </label>
      </div>
    );
  }

  root.components.Dropzone = Dropzone;
})();

