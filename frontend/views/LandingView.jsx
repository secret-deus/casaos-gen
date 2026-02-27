(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.views = root.views || {};

  function LandingView({
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
    const { StepLoadCompose } = root.steps || {};

    return (
      <div className="view-enter">
        <main className="main">
          <div className="container">
            <StepLoadCompose
              mode={mode}
              onModeChange={onModeChange}
              composeText={composeText}
              composeFile={composeFile}
              onComposeTextChange={onComposeTextChange}
              onComposeFileChange={onComposeFileChange}
              onLoadFromFile={onLoadFromFile}
              onLoadFromText={onLoadFromText}
              engine={engine}
              busy={busy}
            />
          </div>
        </main>

        <footer className="footer">
          <div className="container footer__inner">
            <div className="footer__left">
              <span className="muted">Load a compose file to get started.</span>
            </div>
            <div className="footer__right" />
          </div>
        </footer>
      </div>
    );
  }

  root.views.LandingView = LandingView;
})();
