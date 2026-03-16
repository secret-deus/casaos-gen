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
      <div className="landing-wrap">
        <div className="hero">
          <h2 className="hero__title">CasaOS Studio</h2>
          <p className="hero__subtitle">
            Craft perfect AppStore templates with autonomous intelligence and refined design.
          </p>
        </div>

        <div className="landing-load-box">
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

        <div className="landing-footer">
          <span className="muted">v2.4.0 — Refined Industrial Minimalism</span>
        </div>
      </div>
    );
  }

  root.views.LandingView = LandingView;
})();
