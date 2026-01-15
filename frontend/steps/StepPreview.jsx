(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.steps = root.steps || {};

  const { Card, CardHeader, CardBody, Tabs, Button, CodeViewer } = root.components || {};
  const safeJSONStringify = root.utils?.safeJSONStringify || ((value) => String(value ?? ""));

  function StepPreview({
    engine,
    composeText,
    renderedYaml,
    tab,
    onTabChange,
    onRender,
    busy,
  }) {
    const hasCompose = Boolean(engine?.has_compose);
    const hasMeta = Boolean(engine?.has_meta);
    const hasStage2 = Boolean(engine?.has_stage2);

    const tabs = [
      { key: "compose", label: "Compose", badge: hasCompose ? "Loaded" : "" },
      { key: "meta", label: "Meta", badge: hasMeta ? "Ready" : "" },
      { key: "rendered", label: "Rendered", badge: hasStage2 ? "OK" : "" },
    ];

    const renderVariant = hasStage2 ? "secondary" : "primary";

    return (
      <div className="step">
        <Card>
          <CardHeader
            title="Preview & render"
            subtitle="Read-only previews. Render generates multi-language x-casaos output."
            actions={
              <Button
                variant={renderVariant}
                loading={busy?.rendering}
                disabled={!hasCompose}
                onClick={() => onRender?.()}
              >
                {hasStage2 ? "Render again" : "Render"}
              </Button>
            }
          />
          <CardBody>
            <div className="stack stack--md">
              <Tabs value={tab} onValueChange={onTabChange} items={tabs} ariaLabel="Preview tabs" />

              {tab === "compose" && (
                <CodeViewer
                  value={composeText}
                  placeholder="No compose text loaded yet. Load a file or paste YAML in Step 1."
                  maxHeight={520}
                />
              )}

              {tab === "meta" && (
                <CodeViewer value={safeJSONStringify(engine?.meta)} placeholder="No metadata yet." maxHeight={520} />
              )}

              {tab === "rendered" && (
                <CodeViewer
                  value={renderedYaml}
                  placeholder={
                    hasStage2
                      ? "Rendered output exists on the server. Click Export to fetch YAML."
                      : "Not rendered yet. Click Render."
                  }
                  maxHeight={520}
                />
              )}
            </div>
          </CardBody>
        </Card>
      </div>
    );
  }

  root.steps.StepPreview = StepPreview;
})();

