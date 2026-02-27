(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.steps = root.steps || {};

  const { Card, CardHeader, CardBody, Button, CodeViewer, Field, Input, Select, Textarea, Checkbox } =
    root.components || {};

  function resolveMetaValue(engine, target) {
    const meta = engine?.meta;
    if (!meta) {
      return "";
    }

    const rawTarget = String(target || "").trim();
    if (!rawTarget) {
      return "";
    }

    if (rawTarget.startsWith("app.")) {
      const field = rawTarget.slice("app.".length);
      if (!field || field.includes(".")) {
        return "";
      }
      return String(meta?.app?.[field] ?? "");
    }

    const parts = rawTarget.split(":");
    if (parts.length < 4 || parts[0] !== "service") {
      return "";
    }
    const serviceName = parts[1];
    const fieldType = parts[2];
    const identifier = parts.slice(3).join(":");
    const service = meta?.services?.[serviceName];
    if (!service) {
      return "";
    }

    const listName = { env: "envs", port: "ports", volume: "volumes" }[fieldType];
    if (!listName) {
      return "";
    }

    const items = Array.isArray(service[listName]) ? service[listName] : [];
    const match = items.find((item) => String(item?.container ?? "") === identifier);
    return String(match?.description ?? "");
  }

  function classifyTarget(target) {
    const rawTarget = String(target || "").trim();
    if (!rawTarget) {
      return { kind: "invalid" };
    }

    if (rawTarget.startsWith("app.")) {
      const fieldPath = rawTarget.slice("app.".length);
      const multiLanguageFields = new Set(["title", "tagline", "description"]);
      const singleLanguageFields = new Set([
        "category",
        "author",
        "developer",
        "main",
        "port_map",
        "scheme",
        "index",
        "icon",
        "thumbnail",
      ]);

      if (multiLanguageFields.has(fieldPath) || fieldPath.startsWith("tips.")) {
        return { kind: "app_multilang", fieldPath };
      }
      if (singleLanguageFields.has(fieldPath)) {
        return { kind: "app_single", fieldPath };
      }
      return { kind: "app_unknown", fieldPath };
    }

    if (rawTarget.startsWith("service:")) {
      const parts = rawTarget.split(":");
      if (parts.length >= 4 && ["env", "port", "volume"].includes(parts[2])) {
        return { kind: "service_multilang", serviceName: parts[1], fieldType: parts[2], identifier: parts.slice(3).join(":") };
      }
      if (parts.length >= 3) {
        return { kind: "service_single" };
      }
      return { kind: "invalid" };
    }

    return { kind: "unknown" };
  }

  /* ─── QuickUpdateCard ─── */
  function QuickUpdateCard({ engine, onQuickUpdate, busy }) {
    const { useEffect, useState } = React;
    const [presetId, setPresetId] = useState("app.description|multi");
    const [targetDraft, setTargetDraft] = useState("app.description");
    const [multilang, setMultilang] = useState(true);
    const [languageDraft, setLanguageDraft] = useState("");
    const [valueDraft, setValueDraft] = useState("");
    const [isDirtyValue, setIsDirtyValue] = useState(false);
    const [isDirtyTarget, setIsDirtyTarget] = useState(false);

    const canExport = Boolean(engine?.has_compose && (engine?.has_meta || engine?.has_stage2));
    const canPatch = canExport && typeof onQuickUpdate === "function";

    const appPresetsMulti = [
      { id: "app.title|multi", label: "app.title", target: "app.title", multilang: true },
      { id: "app.tagline|multi", label: "app.tagline", target: "app.tagline", multilang: true },
      { id: "app.description|multi", label: "app.description", target: "app.description", multilang: true },
      { id: "app.tips.before_install|multi", label: "app.tips.before_install", target: "app.tips.before_install", multilang: true },
      { id: "app.tips.after_install|multi", label: "app.tips.after_install", target: "app.tips.after_install", multilang: true },
    ];

    const appPresetsSingle = [
      { id: "app.category|single", label: "app.category", target: "app.category", multilang: false },
      { id: "app.author|single", label: "app.author", target: "app.author", multilang: false },
      { id: "app.main|single", label: "app.main", target: "app.main", multilang: false },
      { id: "app.port_map|single", label: "app.port_map", target: "app.port_map", multilang: false },
      { id: "app.scheme|single", label: "app.scheme", target: "app.scheme", multilang: false },
      { id: "app.index|single", label: "app.index", target: "app.index", multilang: false },
    ];

    const servicePresets = (() => {
      const meta = engine?.meta;
      const services = meta?.services || {};
      const out = [];
      for (const [serviceName, svc] of Object.entries(services)) {
        const envs = Array.isArray(svc?.envs) ? svc.envs : [];
        const ports = Array.isArray(svc?.ports) ? svc.ports : [];
        const volumes = Array.isArray(svc?.volumes) ? svc.volumes : [];

        for (const entry of ports) {
          const container = String(entry?.container ?? "");
          if (!container) continue;
          out.push({
            id: `service:${serviceName}:port:${container}|multi`,
            label: `service:${serviceName}:port:${container}`,
            target: `service:${serviceName}:port:${container}`,
            multilang: true,
          });
        }
        for (const entry of envs) {
          const container = String(entry?.container ?? "");
          if (!container) continue;
          out.push({
            id: `service:${serviceName}:env:${container}|multi`,
            label: `service:${serviceName}:env:${container}`,
            target: `service:${serviceName}:env:${container}`,
            multilang: true,
          });
        }
        for (const entry of volumes) {
          const container = String(entry?.container ?? "");
          if (!container) continue;
          out.push({
            id: `service:${serviceName}:volume:${container}|multi`,
            label: `service:${serviceName}:volume:${container}`,
            target: `service:${serviceName}:volume:${container}`,
            multilang: true,
          });
        }
      }
      return out;
    })();

    const activeMetaValue = resolveMetaValue(engine, targetDraft);

    const targetType = classifyTarget(targetDraft);
    const lockedMultilang =
      targetType.kind === "service_multilang" || targetType.kind === "app_multilang"
        ? true
        : targetType.kind === "service_single" || targetType.kind === "app_single"
          ? false
          : null;
    const multilangLocked = lockedMultilang != null;
    const effectiveMultilang = multilangLocked ? lockedMultilang : Boolean(multilang);

    useEffect(() => {
      if (!multilangLocked) return;
      setMultilang(lockedMultilang);
    }, [multilangLocked, lockedMultilang]);

    useEffect(() => {
      if (isDirtyValue) return;
      setValueDraft(activeMetaValue);
    }, [activeMetaValue, isDirtyValue]);

    const languageOptions = Array.isArray(engine?.languages) ? engine.languages : [];
    useEffect(() => {
      if (!effectiveMultilang) return;
      if (!languageOptions.length) return;
      setLanguageDraft((current) => {
        const currentValue = String(current || "").trim();
        if (!currentValue) return "";
        if (currentValue && languageOptions.includes(currentValue)) return currentValue;
        if (languageOptions.includes("zh_CN")) return "zh_CN";
        if (languageOptions.includes("en_US")) return "en_US";
        return languageOptions[0];
      });
    }, [effectiveMultilang, engine?.languages]);

    return (
      <Card>
        <CardHeader
          title="Quick update"
          subtitle="Patch a single field without re-running the full pipeline. Multi-language fields auto-translate via LLM on Apply."
          actions={
            <Button
              variant="primary"
              size="md"
              loading={busy?.patchingField}
              disabled={!canPatch || !String(targetDraft || "").trim()}
              onClick={async () => {
                const ok = await onQuickUpdate?.({
                  target: targetDraft,
                  value: valueDraft,
                  multilang: effectiveMultilang,
                  language: languageDraft,
                });
                if (ok) {
                  setIsDirtyValue(false);
                  setIsDirtyTarget(false);
                }
              }}
            >
              Apply
            </Button>
          }
        />
        <CardBody>
          <div className="stack stack--md">
            <div className="grid2">
              <Field id="quick-preset" label="Preset">
                <Select
                  id="quick-preset"
                  value={presetId}
                  disabled={!canPatch}
                  onChange={(event) => {
                    const next = event.target.value;
                    setPresetId(next);
                    const allPresets = [...appPresetsMulti, ...appPresetsSingle, ...servicePresets];
                    const match = allPresets.find((item) => item.id === next);
                    if (!match) return;
                    setTargetDraft(match.target);
                    setMultilang(Boolean(match.multilang));
                    setIsDirtyTarget(false);
                    setValueDraft(resolveMetaValue(engine, match.target));
                    setIsDirtyValue(false);
                  }}
                >
                  <optgroup label="App (multi-language)">
                    {appPresetsMulti.map((preset) => (
                      <option key={preset.id} value={preset.id}>{preset.label}</option>
                    ))}
                  </optgroup>
                  <optgroup label="App (single-language)">
                    {appPresetsSingle.map((preset) => (
                      <option key={preset.id} value={preset.id}>{preset.label}</option>
                    ))}
                  </optgroup>
                  <optgroup label="Services (multi-language descriptions)">
                    {servicePresets.length ? (
                      servicePresets.map((preset) => (
                        <option key={preset.id} value={preset.id}>{preset.label}</option>
                      ))
                    ) : (
                      <option value="__no_services__" disabled>(no services detected)</option>
                    )}
                  </optgroup>
                </Select>
              </Field>

              <div className="stack stack--md">
                {multilangLocked ? (
                  <div className="muted">
                    {effectiveMultilang ? "Field type: multi-language" : "Field type: single-language"}
                  </div>
                ) : (
                  <Checkbox
                    id="quick-multilang"
                    label="Multi-language field"
                    hint="When enabled, edits write into x-casaos locale dictionaries."
                    checked={effectiveMultilang}
                    disabled={!canPatch}
                    onChange={(checked) => setMultilang(Boolean(checked))}
                  />
                )}

                {effectiveMultilang && (
                  <Field
                    id="quick-language"
                    label="Input language (optional)"
                    hint="Leave as auto to detect from your text. Set it only if detection is wrong."
                  >
                    <Select
                      id="quick-language"
                      value={languageDraft}
                      disabled={!canPatch || !languageOptions.length}
                      onChange={(event) => setLanguageDraft(event.target.value)}
                    >
                      <option value="">auto</option>
                      {languageOptions.length ? (
                        languageOptions.map((lang) => (
                          <option key={lang} value={lang}>{lang}</option>
                        ))
                      ) : (
                        <option value="" disabled>(no languages)</option>
                      )}
                    </Select>
                  </Field>
                )}
              </div>
            </div>

            <Field
              id="quick-target"
              label="Target"
              hint="Examples: app.description, app.tips.before_install, service:web:port:80, service:web:env:TZ"
            >
              <Input
                id="quick-target"
                value={targetDraft}
                onChange={(event) => {
                  setTargetDraft(event.target.value);
                  setIsDirtyTarget(true);
                }}
                placeholder="app.description"
                disabled={!canPatch}
              />
            </Field>

            <Field id="quick-value" label="Value" hint={activeMetaValue ? "Prefilled from the loaded file/server metadata." : ""}>
              <Textarea
                id="quick-value"
                value={valueDraft}
                onChange={(event) => {
                  setValueDraft(event.target.value);
                  setIsDirtyValue(true);
                }}
                rows={6}
                spellCheck={false}
                disabled={!canPatch}
              />
            </Field>

            <div className="inlineNotice">
              {effectiveMultilang
                ? "Multi-language mode uses the LLM to translate and fill all locales automatically."
                : "Single-language mode updates the raw field value."}{" "}
              Export will generate <code>x-casaos</code> automatically if missing (no LLM required).
            </div>
          </div>
        </CardBody>
      </Card>
    );
  }

  /* ─── ExportCard ─── */
  function ExportCard({ engine, renderedYaml, onRefresh, busy }) {
    const hasStage2 = Boolean(engine?.has_stage2);
    const canExport = Boolean(engine?.has_compose && (engine?.has_meta || engine?.has_stage2));

    return (
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
                disabled={!canExport}
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
                <div className="banner__title">Not exported yet</div>
                <div className="banner__message">
                  Click Refresh YAML to generate multi-language <code>x-casaos</code> output (no LLM required).
                </div>
              </div>
            )}

            <CodeViewer value={renderedYaml} placeholder="Exported YAML will appear here." maxHeight={520} />
          </div>
        </CardBody>
      </Card>
    );
  }

  /* ─── StepExport (combined, backward-compatible) ─── */
  function StepExport({ engine, renderedYaml, onRefresh, onQuickUpdate, busy }) {
    return (
      <div className="step">
        <div className="stack stack--lg">
          <QuickUpdateCard engine={engine} onQuickUpdate={onQuickUpdate} busy={busy} />
          <ExportCard engine={engine} renderedYaml={renderedYaml} onRefresh={onRefresh} busy={busy} />
        </div>
      </div>
    );
  }

  root.steps.QuickUpdateCard = QuickUpdateCard;
  root.steps.ExportCard = ExportCard;
  root.steps.StepExport = StepExport;
})();
