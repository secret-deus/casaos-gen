(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.steps = root.steps || {};

  const { Card, CardHeader, CardBody, Button, CodeViewer } = root.components || {};

  function StepExport({ engine, renderedYaml, onRefresh, busy }) {
    const hasStage2 = Boolean(engine?.has_stage2);

    return (
      <div className="step">
        <Card>
          <CardHeader
            title="Export"
            subtitle="Copy or download the final CasaOS compose YAML."
            actions={
              <div className="row row--end">
                <Button
                  variant="secondary"
                  size="md"
                  loading={busy?.exporting}
                  disabled={!hasStage2}
                  onClick={() => onRefresh?.()}
                >
                  Refresh YAML
                </Button>
              </div>
            }
          />
          <CardBody>
            <div className="stack stack--lg">
              {hasStage2 ? (
                <div className="banner banner--success">
                  <div className="banner__title">Rendered successfully</div>
                  <div className="banner__message">
                    YAML below is exported in AppStore-friendly format (ports long syntax + bind volumes).
                  </div>
                </div>
              ) : (
                <div className="banner banner--warning">
                  <div className="banner__title">Nothing to export yet</div>
                  <div className="banner__message">Go back to Preview and click Render first.</div>
                </div>
              )}

              <CodeViewer value={renderedYaml} placeholder="Exported YAML will appear here." maxHeight={520} />
            </div>
          </CardBody>
        </Card>
      </div>
    );
  }

  root.steps.StepExport = StepExport;
})();
