(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.views = root.views || {};

  function QuickEditView({
    engine,
    renderedYaml,
    onRefresh,
    onQuickUpdate,
    onBackToLanding,
    downloadYaml,
    copyYaml,
    busy,
  }) {
    const { Button } = root.components || {};
    const { QuickUpdateCard, ExportCard } = root.steps || {};

    return (
      <div className="view-enter">
        <main className="main">
          <div className="container">
            <div className="quickEditView">
              <div className="quickEditView__header">
                <h2 className="quickEditView__title">Quick Edit</h2>
                <button className="backLink" type="button" onClick={onBackToLanding}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M19 12H5m0 0l7-7m-7 7l7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Load new file
                </button>
              </div>

              <div className="card-animate card-delay-1">
                <QuickUpdateCard engine={engine} onQuickUpdate={onQuickUpdate} busy={busy} />
              </div>

              <div className="card-animate card-delay-2">
                <ExportCard engine={engine} renderedYaml={renderedYaml} onRefresh={onRefresh} busy={busy} />
              </div>
            </div>
          </div>
        </main>

        <footer className="footer">
          <div className="container footer__inner">
            <div className="footer__left">
              <Button variant="secondary" onClick={onBackToLanding}>
                Back
              </Button>
            </div>
            <div className="footer__right">
              <div className="footer__actions">
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
        </footer>
      </div>
    );
  }

  root.views.QuickEditView = QuickEditView;
})();
