(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.steps = root.steps || {};

  const { Card, CardHeader, CardBody, Tabs, Button, Field, Textarea, Dropzone } = root.components || {};
  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function StatusPill({ tone = "muted", children }) {
    return <span className={cx("pill", `pill--${tone}`)}>{children}</span>;
  }

  function StepLoadCompose({
    mode,
    onModeChange,
    composeText,
    composeFile,
    onComposeTextChange,
    onComposeFileChange,
    onLoadFromFile,
    onLoadFromText,
    engine,
    busy,
  }) {
    const tabs = [
      { key: "upload", label: "Upload" },
      { key: "paste", label: "Paste YAML" },
    ];

    const canLoadText = Boolean((composeText || "").trim());
    const canLoadFile = Boolean(composeFile);

    return (
      <div className="step step--center">
        <Card className="stepCard">
          <CardHeader
            title="Load docker-compose"
            subtitle="Load a docker-compose.yml or an already-edited CasaOS YAML (with x-casaos). We’ll parse it and prepare the server state."
            actions={
              <div className="pillRow">
                <StatusPill tone={engine?.has_compose ? "success" : "muted"}>
                  {engine?.has_compose ? "Loaded" : "Not loaded"}
                </StatusPill>
              </div>
            }
          />
          <CardBody>
            <Tabs value={mode} onValueChange={onModeChange} items={tabs} ariaLabel="Load mode" />

            {mode === "upload" ? (
              <div className="stack stack--lg">
                <Dropzone
                  id="compose-upload"
                  file={composeFile}
                  onFileChange={onComposeFileChange}
                  accept=".yml,.yaml"
                  disabled={busy}
                  title="Drop compose file"
                  description="Supports docker-compose.yml, or CasaOS output YAML with x-casaos"
                />
                <div className="row row--end">
                  <Button
                    variant="primary"
                    loading={busy}
                    disabled={!canLoadFile}
                    onClick={() => onLoadFromFile?.()}
                  >
                    Load Compose
                  </Button>
                </div>
              </div>
            ) : (
              <div className="stack stack--lg">
                <Field
                  id="compose-text"
                  label="Compose YAML"
                  hint="Paste docker-compose.yml or CasaOS YAML. Empty content disables the load action."
                >
                  <Textarea
                    id="compose-text"
                    value={composeText}
                    onChange={(event) => onComposeTextChange?.(event.target.value)}
                    placeholder="version: '3.8'\nservices:\n  app:\n    image: ...\n"
                    rows={12}
                    spellCheck={false}
                    disabled={busy}
                  />
                </Field>
                <div className="row row--end">
                  <Button
                    variant="primary"
                    loading={busy}
                    disabled={!canLoadText}
                    onClick={() => onLoadFromText?.()}
                  >
                    Load Compose
                  </Button>
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    );
  }

  root.steps.StepLoadCompose = StepLoadCompose;
})();
