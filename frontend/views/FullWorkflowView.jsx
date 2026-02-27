(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.views = root.views || {};

  const { useMemo, useRef } = React;

  const FULL_STEPS = [
    { key: "metadata", label: "Metadata" },
    { key: "preview", label: "Preview" },
    { key: "export", label: "Export" },
  ];

  function FullWorkflowView({
    state,
    dispatch,
    stepIndex,
    maxEnabledIndex,
    onBack,
    onContinue,
    canContinue,
    downloadYaml,
    copyYaml,
    // Step-specific handlers
    fillMetadata,
    saveLLMSettings,
    renderStage2,
    refreshExportYaml,
  }) {
    const { Button, Stepper, AnimatedContainer } = root.components || {};
    const { StepMetadata, StepPreview, ExportCard } = root.steps || {};
    const { clamp } = root.utils || {};

    const prevStepRef = useRef(stepIndex);

    const direction = stepIndex >= prevStepRef.current ? "forward" : "backward";
    // Update ref after computing direction
    if (prevStepRef.current !== stepIndex) {
      prevStepRef.current = stepIndex;
    }

    const animClass = direction === "forward" ? "step-forward" : "step-backward";

    const stepContent = useMemo(() => {
      switch (stepIndex) {
        case 0:
          return (
            <StepMetadata
              engine={state.engine}
              useLLM={state.params.useLLM}
              useParams={state.params.useParams}
              autoRenderAfterSave={state.params.autoRenderAfterSave}
              onUseLLMChange={(value) => dispatch({ type: "SET_PARAMS_MODE", key: "useLLM", value })}
              onUseParamsChange={(value) => dispatch({ type: "SET_PARAMS_MODE", key: "useParams", value })}
              onAutoRenderChange={(value) => dispatch({ type: "SET_PARAMS_MODE", key: "autoRenderAfterSave", value })}
              metadataDraft={state.params.draft}
              onMetadataFieldChange={(field, value) => dispatch({ type: "SET_PARAMS_DRAFT_FIELD", field, value })}
              paramsFile={state.params.file}
              onParamsFileChange={(file) => dispatch({ type: "SET_PARAMS_FILE", file })}
              llmDraft={state.llm.draft}
              onLLMFieldChange={(field, value) => {
                if (field === "temperature") {
                  dispatch({ type: "SET_LLM_DRAFT_FIELD", field, value: clamp(value, 0, 2) });
                  return;
                }
                dispatch({ type: "SET_LLM_DRAFT_FIELD", field, value });
              }}
              onSaveLLMSettings={saveLLMSettings}
              onFillMetadata={fillMetadata}
              busy={{
                fillingMeta: state.busy.fillingMeta,
                savingLLM: state.busy.savingLLM,
                rendering: state.busy.rendering,
              }}
            />
          );
        case 1:
          return (
            <StepPreview
              engine={state.engine}
              composeText={state.compose.text}
              renderedYaml={state.renderedYaml}
              tab={state.preview.tab}
              onTabChange={(tab) => dispatch({ type: "SET_PREVIEW_TAB", tab })}
              onRender={renderStage2}
              busy={{ rendering: state.busy.rendering }}
            />
          );
        case 2:
          return (
            <ExportCard
              engine={state.engine}
              renderedYaml={state.renderedYaml}
              onRefresh={refreshExportYaml}
              busy={{ exporting: state.busy.exporting }}
            />
          );
        default:
          return null;
      }
    }, [state, stepIndex]);

    const footerRight = useMemo(() => {
      if (stepIndex === 2) {
        return (
          <div className="footer__actions">
            <Button
              variant="secondary"
              disabled={!state.engine.has_compose || !state.renderedYaml.trim()}
              onClick={downloadYaml}
            >
              Download
            </Button>
            <Button
              variant="primary"
              disabled={!state.engine.has_compose || !state.renderedYaml.trim()}
              onClick={copyYaml}
            >
              Copy YAML
            </Button>
          </div>
        );
      }
      return (
        <Button variant="primary" disabled={!canContinue} onClick={onContinue}>
          Continue
        </Button>
      );
    }, [stepIndex, state.engine.has_compose, state.renderedYaml, canContinue]);

    return (
      <div className="view-enter">
        <div className="stepperWrap">
          <div className="container">
            <Stepper
              steps={FULL_STEPS}
              activeIndex={stepIndex}
              maxEnabledIndex={maxEnabledIndex}
              onStepChange={(index) => dispatch({ type: "SET_STEP", stepIndex: index })}
            />
          </div>
        </div>

        <main className="main">
          <div className="container">
            <AnimatedContainer animationKey={stepIndex} className={animClass}>
              {stepContent}
            </AnimatedContainer>
          </div>
        </main>

        <footer className="footer">
          <div className="container footer__inner">
            <div className="footer__left">
              <Button variant="secondary" onClick={onBack}>
                Back
              </Button>
            </div>
            <div className="footer__right">{footerRight}</div>
          </div>
        </footer>
      </div>
    );
  }

  root.views.FullWorkflowView = FullWorkflowView;
})();
