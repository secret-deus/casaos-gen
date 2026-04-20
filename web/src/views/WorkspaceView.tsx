import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Accordion } from "../components/Accordion";
import { PreviewPanel } from "../components/PreviewPanel";
import { ServicesEditor } from "../components/ServicesEditor";
import type { ApiState, AppMeta, ServiceDescriptionChange } from "../types";
import type { PreviewTab } from "../store/workspace";

const optionalUrl = z.union([z.literal(""), z.string().url("Enter a valid URL")]);

const appSchema = z.object({
  title: z.string().trim().min(1, "Title is required"),
  tagline: z.string(),
  description: z.string(),
  releaseNotes: z.string(),
  category: z.string(),
  author: z.string(),
  developer: z.string(),
  version: z.string(),
  updateAt: z.union([z.literal(""), z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Use YYYY-MM-DD")]),
  website: optionalUrl,
  repo: optionalUrl,
  support: optionalUrl,
  docs: optionalUrl,
  main: z.string(),
  port_map: z.string(),
  scheme: z.string(),
  index: z.string(),
});

type AppFormValues = z.infer<typeof appSchema>;
type SectionKey = "basic" | "version" | "links" | "runtime" | "services";

interface WorkspaceViewProps {
  state: ApiState;
  composeName: string;
  composeText: string;
  renderedYaml: string;
  warnings: string[];
  previewTab: PreviewTab;
  savingApp: boolean;
  savingServices: boolean;
  rendering: boolean;
  exporting: boolean;
  outputStale: boolean;
  focusTarget: string | null;
  onPreviewTabChange: (tab: PreviewTab) => void;
  onSave: (values: AppFormValues, original: AppMeta) => Promise<void>;
  onSaveServices: (changes: ServiceDescriptionChange[]) => Promise<void>;
  onRender: () => Promise<void>;
  onExport: () => Promise<void>;
  onReset: () => Promise<void>;
  onOpenSettings: () => void;
  onOpenCommandPalette: () => void;
  onFocusHandled: () => void;
}

function serviceDescriptionCount(items: { description: string }[]): number {
  return items.filter((item) => item.description.trim()).length;
}

export function WorkspaceView({
  state,
  composeName,
  composeText,
  renderedYaml,
  warnings,
  previewTab,
  savingApp,
  savingServices,
  rendering,
  exporting,
  outputStale,
  focusTarget,
  onPreviewTabChange,
  onSave,
  onSaveServices,
  onRender,
  onExport,
  onReset,
  onOpenSettings,
  onOpenCommandPalette,
  onFocusHandled,
}: WorkspaceViewProps) {
  const meta = state.meta;
  if (!meta) {
    return null;
  }

  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>({
    basic: true,
    version: false,
    links: false,
    runtime: false,
    services: false,
  });

  const serviceEntries = useMemo(() => Object.entries(meta.services), [meta.services]);
  const { register, handleSubmit, reset, formState } = useForm<AppFormValues>({
    resolver: zodResolver(appSchema),
    defaultValues: meta.app,
  });

  useEffect(() => {
    reset(meta.app);
  }, [meta.app, reset]);

  useEffect(() => {
    if (!focusTarget) {
      return;
    }

    const section: SectionKey = focusTarget.startsWith("service:")
      ? "services"
      : ["version", "updateAt", "releaseNotes"].includes(focusTarget.replace("app.", ""))
        ? "version"
        : ["website", "repo", "support", "docs"].includes(focusTarget.replace("app.", ""))
          ? "links"
          : ["main", "port_map", "scheme", "index"].includes(focusTarget.replace("app.", ""))
            ? "runtime"
            : "basic";

    setOpenSections((current) => ({ ...current, [section]: true }));

    const timer = window.setTimeout(() => {
      const targetElement = Array.from(document.querySelectorAll<HTMLElement>("[data-focus-target]"))
        .find((element) => element.dataset.focusTarget === focusTarget);
      if (targetElement) {
        targetElement.scrollIntoView({ behavior: "smooth", block: "center" });
        targetElement.focus({ preventScroll: true });
      }
      onFocusHandled();
    }, 120);

    return () => window.clearTimeout(timer);
  }, [focusTarget, onFocusHandled]);

  return (
    <div className="workspace">
      <header className="workspaceHeader">
        <div>
          <div className="workspaceHeader__eyebrow">Unified workspace</div>
          <h1>{composeName || meta.app.title || "Untitled compose"}</h1>
          <p>
            Edit app metadata on the left, inspect generated output on the right, and render/export when you are
            ready.
          </p>
          <div className="workspaceHeader__shortcuts">Shortcuts: Cmd/Ctrl + K jump, Cmd/Ctrl + Enter render, Cmd/Ctrl + Shift + E export.</div>
        </div>

        <div className="workspaceHeader__actions">
          <button className="secondaryButton" type="button" onClick={onReset}>
            New compose
          </button>
          <button className="secondaryButton" type="button" onClick={onOpenSettings}>
            LLM settings
          </button>
          <button className="secondaryButton" type="button" onClick={onOpenCommandPalette}>
            Jump to field
          </button>
          <button className="secondaryButton" type="button" disabled={rendering} onClick={() => void onRender()}>
            {rendering ? "Rendering..." : "Render"}
          </button>
          <button
            className="primaryButton"
            type="button"
            disabled={exporting || outputStale}
            onClick={() => void onExport()}
            title={outputStale ? "Render again to refresh YAML after metadata changes." : undefined}
          >
            {outputStale ? "Render to export" : exporting ? "Exporting..." : "Export YAML"}
          </button>
        </div>
      </header>

      <div className="workspaceGrid">
        <form className="inspector" onSubmit={handleSubmit((values) => onSave(values, meta.app))}>
          <div className="inspector__toolbar">
            <span>
              {outputStale
                ? "Metadata changed. Render again to refresh final YAML."
                : formState.isDirty
                  ? "Unsaved changes"
                  : "Up to date"}
            </span>
            <button className="primaryButton" type="submit" disabled={savingApp || !formState.isDirty}>
              {savingApp ? "Saving..." : "Save metadata"}
            </button>
          </div>

          <Accordion
            title="Basic info"
            subtitle="Core app copy and ownership fields"
            open={openSections.basic}
            onOpenChange={(open) => setOpenSections((current) => ({ ...current, basic: open }))}
          >
            <div className="formGrid">
              <label className="field">
                <span>Title</span>
                <input data-focus-target="app.title" {...register("title")} />
                {formState.errors.title ? <small>{formState.errors.title.message}</small> : null}
              </label>
              <label className="field">
                <span>Category</span>
                <input data-focus-target="app.category" {...register("category")} />
              </label>
              <label className="field field--wide">
                <span>Tagline</span>
                <input data-focus-target="app.tagline" {...register("tagline")} />
              </label>
              <label className="field field--wide">
                <span>Description</span>
                <textarea data-focus-target="app.description" {...register("description")} rows={7} spellCheck={false} />
              </label>
              <label className="field">
                <span>Author</span>
                <input data-focus-target="app.author" {...register("author")} />
              </label>
              <label className="field">
                <span>Developer</span>
                <input data-focus-target="app.developer" {...register("developer")} />
              </label>
            </div>
          </Accordion>

          <Accordion
            title="Version & release"
            subtitle="Store-facing release metadata"
            open={openSections.version}
            onOpenChange={(open) => setOpenSections((current) => ({ ...current, version: open }))}
          >
            <div className="formGrid">
              <label className="field">
                <span>Version</span>
                <input data-focus-target="app.version" {...register("version")} placeholder="1.0.0" />
              </label>
              <label className="field">
                <span>Update date</span>
                <input data-focus-target="app.updateAt" {...register("updateAt")} placeholder="2026-03-01" />
                {formState.errors.updateAt ? <small>{formState.errors.updateAt.message}</small> : null}
              </label>
              <label className="field field--wide">
                <span>Release notes</span>
                <textarea data-focus-target="app.releaseNotes" {...register("releaseNotes")} rows={5} spellCheck={false} />
              </label>
            </div>
          </Accordion>

          <Accordion
            title="Links & docs"
            subtitle="Public resources shown in app metadata"
            open={openSections.links}
            onOpenChange={(open) => setOpenSections((current) => ({ ...current, links: open }))}
          >
            <div className="formGrid">
              <label className="field">
                <span>Website</span>
                <input data-focus-target="app.website" {...register("website")} placeholder="https://example.com" />
                {formState.errors.website ? <small>{formState.errors.website.message}</small> : null}
              </label>
              <label className="field">
                <span>Repository</span>
                <input data-focus-target="app.repo" {...register("repo")} placeholder="https://github.com/example/app" />
                {formState.errors.repo ? <small>{formState.errors.repo.message}</small> : null}
              </label>
              <label className="field">
                <span>Support</span>
                <input data-focus-target="app.support" {...register("support")} placeholder="https://github.com/example/app/issues" />
                {formState.errors.support ? <small>{formState.errors.support.message}</small> : null}
              </label>
              <label className="field">
                <span>Docs</span>
                <input data-focus-target="app.docs" {...register("docs")} placeholder="https://docs.example.com" />
                {formState.errors.docs ? <small>{formState.errors.docs.message}</small> : null}
              </label>
            </div>
          </Accordion>

          <Accordion
            title="Runtime routing"
            subtitle="CasaOS launch behavior"
            open={openSections.runtime}
            onOpenChange={(open) => setOpenSections((current) => ({ ...current, runtime: open }))}
          >
            <div className="formGrid">
              <label className="field">
                <span>Main service</span>
                <input data-focus-target="app.main" {...register("main")} />
              </label>
              <label className="field">
                <span>Port map</span>
                <input data-focus-target="app.port_map" {...register("port_map")} />
              </label>
              <label className="field">
                <span>Scheme</span>
                <input data-focus-target="app.scheme" {...register("scheme")} />
              </label>
              <label className="field">
                <span>Index</span>
                <input data-focus-target="app.index" {...register("index")} />
              </label>
            </div>
          </Accordion>

          <Accordion
            title="Services"
            subtitle="Edit env, port, and volume descriptions"
            open={openSections.services}
            onOpenChange={(open) => setOpenSections((current) => ({ ...current, services: open }))}
          >
            <div className="serviceList">
              {serviceEntries.map(([name, service]) => (
                <article key={name} className="serviceCard">
                  <div className="serviceCard__title">{name}</div>
                  <div className="serviceCard__meta">
                    <span>{service.envs.length} envs</span>
                    <span>{service.ports.length} ports</span>
                    <span>{service.volumes.length} volumes</span>
                  </div>
                  <div className="serviceCard__desc">
                    {serviceDescriptionCount(service.envs) + serviceDescriptionCount(service.ports) + serviceDescriptionCount(service.volumes)}
                    {" "}
                    described fields available in metadata.
                  </div>
                </article>
              ))}
            </div>
            <ServicesEditor services={meta.services} saving={savingServices} onSave={onSaveServices} />
          </Accordion>
        </form>

        <PreviewPanel
          tab={previewTab}
          onTabChange={onPreviewTabChange}
          composeText={composeText}
          renderedYaml={renderedYaml}
          meta={meta}
          warnings={warnings}
        />
      </div>
    </div>
  );
}
