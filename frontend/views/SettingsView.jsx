(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.views = root.views || {};

  function SettingsView({ llm, onFieldChange, onSave, onBack, busy }) {
    const { useState, useEffect } = React;
    const { Card, CardHeader, CardBody, Button, Field, Input, Select } = root.components || {};

    const modelOptions = [
      { value: "gpt-4.1-mini", label: "GPT-4o Mini (Default)" },
      { value: "gpt-4o", label: "GPT-4o" },
      { value: "claude-3-5-sonnet-20240620", label: "Claude 3.5 Sonnet" },
      { value: "deepseek-chat", label: "DeepSeek Chat" },
    ];

    const [selectedOption, setSelectedOption] = useState(() => {
      const match = modelOptions.find((opt) => opt.value === llm.model);
      return match ? llm.model : "custom";
    });

    useEffect(() => {
      const match = modelOptions.find((opt) => opt.value === llm.model);
      setSelectedOption(match ? llm.model : "custom");
    }, [llm.model]);

    const isCustom = selectedOption === "custom";

    return (
      <div className="workflow-content">
        <div className="stack stack--lg">
          <Card>
            <CardHeader
              title="Stage 1 LLM"
              subtitle="Configure only the remote API used for metadata drafting."
              actions={
                <Button variant="secondary" loading={busy} onClick={onSave}>
                  Save Stage 1
                </Button>
              }
            />
            <CardBody>
              <div className="stack stack--md">
                <Field
                  id="settings-base-url"
                  label="API Base URL"
                  hint="Optional. Leave empty for the official OpenAI API."
                >
                  <Input
                    id="settings-base-url"
                    value={llm.base_url || ""}
                    onChange={(e) => onFieldChange("base_url", e.target.value)}
                    placeholder="https://api.openai.com/v1"
                  />
                </Field>

                <Field
                  id="settings-api-key"
                  label="API Key"
                  hint="Saved locally. Leave blank to keep the current key."
                >
                  <Input
                    id="settings-api-key"
                    type="password"
                    value={llm.api_key || ""}
                    onChange={(e) => onFieldChange("api_key", e.target.value)}
                    placeholder="sk-..."
                  />
                </Field>

                <div className="grid2">
                  <Field id="settings-model" label="Model Provider">
                    <Select
                      id="settings-model"
                      value={selectedOption}
                      onChange={(e) => {
                        const val = e.target.value;
                        setSelectedOption(val);
                        if (val !== "custom") {
                          onFieldChange("model", val);
                        }
                      }}
                    >
                      {modelOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                      <option value="custom">Custom Model ID...</option>
                    </Select>
                  </Field>

                  <Field id="settings-temp" label="Temperature (0-1)">
                    <Input
                      id="settings-temp"
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      value={llm.temperature ?? 0.2}
                      onChange={(e) => onFieldChange("temperature", parseFloat(e.target.value))}
                    />
                  </Field>
                </div>

                {isCustom && (
                  <Field id="settings-custom-model" label="Custom Model ID">
                    <Input
                      id="settings-custom-model"
                      value={llm.model}
                      onChange={(e) => onFieldChange("model", e.target.value)}
                      placeholder="e.g. kimi-k2.5"
                    />
                  </Field>
                )}
              </div>
            </CardBody>
          </Card>

          <div className="banner banner--info">
            <div className="banner__title">Stage 2 Is Fixed</div>
            <div className="banner__message">
              Stage 2 translation always uses local LM Studio at <code>http://127.0.0.1:1234/v1</code> with
              model <code>qwen/qwen3.5-9b</code>. There is no Stage 2 settings panel anymore.
            </div>
          </div>

          <div className="banner banner--info">
            <div className="banner__title">Storage Note</div>
            <div className="banner__message">
              Only Stage 1 settings are saved to <code>llm_config.json</code>.
            </div>
          </div>
        </div>

        <div className="workflow-footer">
          <Button variant="secondary" onClick={onBack}>
            Back
          </Button>
          <div className="workflow-footer__right muted">Stage 2 translation is managed automatically.</div>
        </div>
      </div>
    );
  }

  root.views.SettingsView = SettingsView;
})();
