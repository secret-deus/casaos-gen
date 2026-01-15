(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.steps = root.steps || {};

  const {
    Card,
    CardHeader,
    CardBody,
    Button,
    Field,
    Input,
    Textarea,
    Select,
    Checkbox,
  } = root.components || {};

  const cx = root.utils?.cx || ((...parts) => parts.filter(Boolean).join(" "));

  function StepMetadata({
    engine,
    useLLM,
    useParams,
    autoRenderAfterSave,
    onUseLLMChange,
    onUseParamsChange,
    onAutoRenderChange,
    metadataDraft,
    onMetadataFieldChange,
    paramsFile,
    onParamsFileChange,
    llmDraft,
    onLLMFieldChange,
    onSaveLLMSettings,
    onFillMetadata,
    busy,
  }) {
    const hasCompose = Boolean(engine?.has_compose);
    const metaTitle = engine?.meta?.app?.title || "";

    return (
      <div className="step">
        <div className="columns">
          <Card>
            <CardHeader
              title="Metadata"
              subtitle={
                hasCompose
                  ? "Use params overrides and/or LLM to fill CasaOS metadata before rendering."
                  : "Load a compose file first."
              }
              actions={
                <Button
                  variant="secondary"
                  size="md"
                  loading={busy?.fillingMeta}
                  disabled={!hasCompose || (!useLLM && !useParams)}
                  onClick={() => onFillMetadata?.()}
                >
                  Save Metadata
                </Button>
              }
            />
            <CardBody>
              <div className="stack stack--lg">
                <div className="grid2">
                  <Checkbox
                    id="toggle-params"
                    label="Use Params"
                    hint="Apply your overrides (title/description/store_folder...)"
                    checked={useParams}
                    disabled={!hasCompose}
                    onChange={onUseParamsChange}
                  />
                  <Checkbox
                    id="toggle-llm"
                    label="Use LLM"
                    hint="Let the model draft missing descriptions"
                    checked={useLLM}
                    disabled={!hasCompose}
                    onChange={onUseLLMChange}
                  />
                </div>

                <Checkbox
                  id="toggle-auto-render"
                  label="Auto-render multi-language output"
                  hint="After saving metadata, automatically render x-casaos so Preview is always up-to-date."
                  checked={autoRenderAfterSave}
                  disabled={!hasCompose || busy?.fillingMeta || busy?.rendering}
                  onChange={onAutoRenderChange}
                />

                <div className="divider" role="separator" />

                <div className="section">
                  <div className="section__title">App identity</div>
                  <div className="grid2">
                    <Field id="store_folder" label="App ID / store_folder" hint="Used for AppStore CDN icon/screenshot links.">
                      <Input
                        id="store_folder"
                        value={metadataDraft.store_folder}
                        onChange={(event) => onMetadataFieldChange?.("store_folder", event.target.value)}
                        placeholder="NocoDB"
                        disabled={!hasCompose}
                      />
                    </Field>
                    <Field id="category" label="Category">
                      <Input
                        id="category"
                        value={metadataDraft.category}
                        onChange={(event) => onMetadataFieldChange?.("category", event.target.value)}
                        placeholder="Database"
                        disabled={!hasCompose}
                      />
                    </Field>
                    <Field id="title" label="Title">
                      <Input
                        id="title"
                        value={metadataDraft.title}
                        onChange={(event) => onMetadataFieldChange?.("title", event.target.value)}
                        placeholder={metaTitle || "My App"}
                        disabled={!hasCompose}
                      />
                    </Field>
                    <Field id="tagline" label="Tagline">
                      <Input
                        id="tagline"
                        value={metadataDraft.tagline}
                        onChange={(event) => onMetadataFieldChange?.("tagline", event.target.value)}
                        placeholder="One-line pitch"
                        disabled={!hasCompose}
                      />
                    </Field>
                  </div>
                  <Field id="description" label="Description" hint="Plain text. It will be replicated to all locales unless you customize translations.">
                    <Textarea
                      id="description"
                      value={metadataDraft.description}
                      onChange={(event) => onMetadataFieldChange?.("description", event.target.value)}
                      placeholder="Describe what this app does, prerequisites, and usage notes."
                      rows={6}
                      disabled={!hasCompose}
                    />
                  </Field>
                </div>

                <div className="section">
                  <div className="section__title">Attribution & routing</div>
                  <div className="grid2">
                    <Field id="author" label="Author">
                      <Input
                        id="author"
                        value={metadataDraft.author}
                        onChange={(event) => onMetadataFieldChange?.("author", event.target.value)}
                        placeholder="IceWhaleTech"
                        disabled={!hasCompose}
                      />
                    </Field>
                    <Field id="developer" label="Developer">
                      <Input
                        id="developer"
                        value={metadataDraft.developer}
                        onChange={(event) => onMetadataFieldChange?.("developer", event.target.value)}
                        placeholder="fromxiaobai"
                        disabled={!hasCompose}
                      />
                    </Field>
                    <Field id="main" label="Main service">
                      <Input
                        id="main"
                        value={metadataDraft.main}
                        onChange={(event) => onMetadataFieldChange?.("main", event.target.value)}
                        placeholder="web"
                        disabled={!hasCompose}
                      />
                    </Field>
                    <Field id="port_map" label="Port map">
                      <Input
                        id="port_map"
                        value={metadataDraft.port_map}
                        onChange={(event) => onMetadataFieldChange?.("port_map", event.target.value)}
                        placeholder="8080"
                        disabled={!hasCompose}
                      />
                    </Field>
                    <Field id="scheme" label="Scheme">
                      <Select
                        id="scheme"
                        value={metadataDraft.scheme}
                        onChange={(event) => onMetadataFieldChange?.("scheme", event.target.value)}
                        disabled={!hasCompose}
                      >
                        <option value="">auto</option>
                        <option value="http">http</option>
                        <option value="https">https</option>
                      </Select>
                    </Field>
                    <Field id="index" label="Index path">
                      <Input
                        id="index"
                        value={metadataDraft.index}
                        onChange={(event) => onMetadataFieldChange?.("index", event.target.value)}
                        placeholder="/"
                        disabled={!hasCompose}
                      />
                    </Field>
                  </div>
                </div>

                <div className="section">
                  <div className="section__title">Optional: params.yml file</div>
                  <div className="row row--between row--wrap">
                    <div className="muted">
                      Uploading a params.yml overrides the form fields above (useful when you already have one).
                    </div>
                    <div className="row row--end">
                      <input
                        type="file"
                        accept=".yml,.yaml"
                        disabled={!hasCompose}
                        onChange={(event) => onParamsFileChange?.(event.target.files?.[0] || null)}
                      />
                      {paramsFile && <span className="pill pill--muted">{paramsFile.name}</span>}
                    </div>
                  </div>
                </div>

                <div className={cx("inlineNotice", { "inlineNotice--warning": !useLLM && !useParams })}>
                  {useLLM || useParams
                    ? "Tip: Save Metadata applies Params/LLM to the server state. Preview/Export always reflects the server snapshot."
                    : "Select at least one mode (Params or LLM) to save metadata."}
                </div>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="LLM settings"
              subtitle="Configure the model used for Stage 1 drafting. Settings are saved server-side for this workspace."
              actions={
                <Button
                  variant="secondary"
                  loading={busy?.savingLLM}
                  disabled={!hasCompose}
                  onClick={() => onSaveLLMSettings?.()}
                >
                  Save LLM
                </Button>
              }
            />
            <CardBody>
              <div className="stack stack--lg">
                <div className="grid2">
                  <Field
                    id="llm_base_url"
                    label="Base URL"
                    hint="Leave blank for OpenAI default. Use this for compatible gateways."
                  >
                    <Input
                      id="llm_base_url"
                      value={llmDraft.base_url}
                      onChange={(event) => onLLMFieldChange?.("base_url", event.target.value)}
                      placeholder="https://api.openai.com/v1"
                      disabled={!hasCompose}
                    />
                  </Field>
                  <Field id="llm_api_key" label="API key" hint="Saved server-side. Leave blank to keep existing key.">
                    <Input
                      id="llm_api_key"
                      value={llmDraft.api_key}
                      onChange={(event) => onLLMFieldChange?.("api_key", event.target.value)}
                      placeholder="sk-..."
                      disabled={!hasCompose}
                    />
                  </Field>
                  <Field id="llm_model" label="Model">
                    <Input
                      id="llm_model"
                      value={llmDraft.model}
                      onChange={(event) => onLLMFieldChange?.("model", event.target.value)}
                      placeholder="gpt-4.1-mini"
                      disabled={!hasCompose}
                    />
                  </Field>
                  <Field id="llm_temperature" label="Temperature">
                    <Input
                      id="llm_temperature"
                      type="number"
                      min="0"
                      max="2"
                      step="0.1"
                      value={llmDraft.temperature}
                      onChange={(event) => onLLMFieldChange?.("temperature", event.target.value)}
                      disabled={!hasCompose}
                    />
                  </Field>
                </div>

                <div className="section">
                  <div className="section__title">Prompt template</div>
                  <Field
                    id="llm_prompt_template"
                    label="Prompt Template (local)"
                    hint="Stored in the browser only. Backend prompt wiring is intentionally unchanged to preserve existing APIs."
                  >
                    <Textarea
                      id="llm_prompt_template"
                      value={llmDraft.prompt_template}
                      onChange={(event) => onLLMFieldChange?.("prompt_template", event.target.value)}
                      placeholder="(Optional) Notes for future prompt customization..."
                      rows={5}
                      disabled={!hasCompose}
                    />
                  </Field>
                </div>

                <div className="inlineNotice">
                  Current server config: model <strong>{engine?.llm?.model || "n/a"}</strong>, temp{" "}
                  <strong>{engine?.llm?.temperature ?? "n/a"}</strong>
                </div>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    );
  }

  root.steps.StepMetadata = StepMetadata;
})();
