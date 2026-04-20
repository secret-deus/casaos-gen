import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import type { ApiState } from "../types";

const schema = z.object({
  base_url: z.string(),
  api_key: z.string(),
  model: z.string().min(1, "Model is required"),
  temperature: z.coerce.number().min(0).max(2),
});

type SettingsValues = z.infer<typeof schema>;

interface SettingsDialogProps {
  open: boolean;
  llm: ApiState["llm"];
  saving: boolean;
  onClose: () => void;
  onSubmit: (values: SettingsValues) => Promise<void>;
}

export function SettingsDialog({ open, llm, saving, onClose, onSubmit }: SettingsDialogProps) {
  const { register, handleSubmit, reset, formState } = useForm<SettingsValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      base_url: llm.stage1.base_url || "",
      api_key: "",
      model: llm.stage1.model,
      temperature: llm.stage1.temperature,
    },
  });

  useEffect(() => {
    reset({
      base_url: llm.stage1.base_url || "",
      api_key: "",
      model: llm.stage1.model,
      temperature: llm.stage1.temperature,
    });
  }, [llm, reset]);

  if (!open) {
    return null;
  }

  return (
    <div className="dialogBackdrop" role="presentation" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="dialog__header">
          <div>
            <h2>LLM settings</h2>
            <p>Configure Stage 1 fill defaults. Stage 2 remains managed by the backend.</p>
          </div>
          <button className="ghostButton" type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <form className="formGrid" onSubmit={handleSubmit(onSubmit)}>
          <label className="field">
            <span>Base URL</span>
            <input {...register("base_url")} placeholder="https://api.openai.com/v1" />
          </label>

          <label className="field">
            <span>API key</span>
            <input {...register("api_key")} type="password" placeholder="Leave blank to keep current key" />
          </label>

          <label className="field">
            <span>Model</span>
            <input {...register("model")} placeholder="gpt-4.1-mini" />
            {formState.errors.model ? <small>{formState.errors.model.message}</small> : null}
          </label>

          <label className="field">
            <span>Temperature</span>
            <input {...register("temperature")} type="number" min="0" max="2" step="0.1" />
            {formState.errors.temperature ? <small>{formState.errors.temperature.message}</small> : null}
          </label>

          <div className="dialog__footer">
            <button className="primaryButton" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save settings"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
