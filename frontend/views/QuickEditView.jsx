(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.views = root.views || {};

  function QuickEditView({
    engine,
    renderedYaml,
    onRefresh,
    onQuickUpdate,
    downloadYaml,
    copyYaml,
    busy,
  }) {
    const { Button } = root.components || {};
    const { QuickUpdateCard, ExportCard } = root.steps || {};

    return (
      <div className="workflow-content">
        <div className="stack stack--lg">
          <QuickUpdateCard engine={engine} onQuickUpdate={onQuickUpdate} busy={busy} />
          <ExportCard engine={engine} renderedYaml={renderedYaml} onRefresh={onRefresh} busy={busy} />
        </div>

        <div className="workflow-footer">
          <div />
          <div className="workflow-footer__right">
            <div className="row">
              <Button
                variant="secondary"
                disabled={!engine?.has_compose || !renderedYaml?.trim()}
                onClick={downloadYaml}
              >
                Download
              </Button>
              <Button
                variant="primary"
                disabled={!engine?.has_compose || !renderedYaml?.trim()}
                onClick={copyYaml}
              >
                Copy YAML
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  root.views.QuickEditView = QuickEditView;
})();
