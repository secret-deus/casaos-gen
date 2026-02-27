(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.components = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function Stepper({
    steps,
    activeIndex,
    maxEnabledIndex,
    onStepChange,
    className,
    ariaLabel = "Wizard steps",
  }) {
    const stepperStyle = { gridTemplateColumns: `repeat(${steps.length}, 1fr)` };

    return (
      <nav className={cx("stepper", className)} style={stepperStyle} aria-label={ariaLabel}>
        {steps.map((step, index) => {
          const isActive = index === activeIndex;
          const isEnabled = index <= maxEnabledIndex;
          const isComplete = index < maxEnabledIndex && isEnabled && !isActive;

          return (
            <button
              key={step.key}
              type="button"
              className={cx("stepper__step", {
                "stepper__step--active": isActive,
                "stepper__step--complete": isComplete,
                "stepper__step--disabled": !isEnabled,
              })}
              onClick={() => {
                if (!isEnabled) {
                  return;
                }
                onStepChange?.(index);
              }}
              disabled={!isEnabled}
              aria-current={isActive ? "step" : undefined}
            >
              <span className="stepper__marker" aria-hidden="true">
                {isComplete ? "✓" : index + 1}
              </span>
              <span className="stepper__label">{step.label}</span>
            </button>
          );
        })}
      </nav>
    );
  }

  root.components.Stepper = Stepper;
})();
