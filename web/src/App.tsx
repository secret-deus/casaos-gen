import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { exportCompose, getState, loadComposeText, renderCompose, resetSession, saveLlmConfig, updateMetaField } from "./lib/api";
import { CommandPalette, type CommandPaletteItem } from "./components/CommandPalette";
import { LandingView } from "./views/LandingView";
import { WorkspaceView } from "./views/WorkspaceView";
import { SettingsDialog } from "./components/SettingsDialog";
import { useWorkspaceStore } from "./store/workspace";
import type { AppMeta, ServiceDescriptionChange } from "./types";

type AppFormValues = Pick<
  AppMeta,
  | "title"
  | "tagline"
  | "description"
  | "releaseNotes"
  | "category"
  | "author"
  | "developer"
  | "version"
  | "updateAt"
  | "website"
  | "repo"
  | "support"
  | "docs"
  | "main"
  | "port_map"
  | "scheme"
  | "index"
>;

function downloadYaml(text: string, filename: string) {
  const blob = new Blob([text], { type: "text/yaml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const queryClient = useQueryClient();
  const [latestWarnings, setLatestWarnings] = useState<string[]>([]);
  const [outputStale, setOutputStale] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [focusTarget, setFocusTarget] = useState<string | null>(null);
  const stateQuery = useQuery({ queryKey: ["state"], queryFn: getState });
  const exportQuery = useQuery({
    queryKey: ["export-compose", stateQuery.data?.has_stage2],
    queryFn: exportCompose,
    enabled: Boolean(stateQuery.data?.has_stage2),
  });

  const composeName = useWorkspaceStore((state) => state.composeName);
  const previewTab = useWorkspaceStore((state) => state.previewTab);
  const settingsOpen = useWorkspaceStore((state) => state.settingsOpen);
  const notice = useWorkspaceStore((state) => state.notice);
  const setComposeName = useWorkspaceStore((state) => state.setComposeName);
  const setPreviewTab = useWorkspaceStore((state) => state.setPreviewTab);
  const setSettingsOpen = useWorkspaceStore((state) => state.setSettingsOpen);
  const setNotice = useWorkspaceStore((state) => state.setNotice);

  useEffect(() => {
    const state = stateQuery.data;
    if (!state?.meta?.app) {
      return;
    }
    if (!composeName.trim()) {
      setComposeName(`${state.meta.app.title || state.meta.app.main || "compose"}.yml`);
    }
  }, [composeName, setComposeName, stateQuery.data]);

  useEffect(() => {
    if (exportQuery.error instanceof Error) {
      setNotice({ tone: "error", message: exportQuery.error.message });
    }
  }, [exportQuery.error, setNotice]);

  const importMutation = useMutation({
    mutationFn: loadComposeText,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      setLatestWarnings([]);
      setOutputStale(false);
      setPreviewTab("meta");
      setNotice({ tone: "success", message: "Compose loaded into the workspace." });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "Failed to load compose." });
    },
  });

  const saveMutation = useMutation({
    mutationFn: async ({ values, original }: { values: AppFormValues; original: AppMeta }) => {
      const changedEntries = Object.entries(values).filter(([key, value]) => value !== original[key as keyof AppMeta]);
      for (const [key, value] of changedEntries) {
        await updateMetaField(`app.${key}`, value);
      }
      return changedEntries.length;
    },
    onSuccess: async (count) => {
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      setPreviewTab("meta");
      if (count > 0 && state?.has_stage2) {
        setOutputStale(true);
      }
      const suffix = count > 0 && state?.has_stage2 ? " Render again to refresh YAML output." : "";
      setNotice({
        tone: "success",
        message: count ? `Saved ${count} metadata field(s).${suffix}` : "No metadata changes to save.",
      });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "Failed to save metadata." });
    },
  });

  const saveServicesMutation = useMutation({
    mutationFn: async (changes: ServiceDescriptionChange[]) => {
      for (const change of changes) {
        await updateMetaField(change.target, change.value);
      }
      return changes.length;
    },
    onSuccess: async (count) => {
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      setPreviewTab("meta");
      if (count > 0 && state?.has_stage2) {
        setOutputStale(true);
      }
      const suffix = count > 0 && state?.has_stage2 ? " Render again to refresh YAML output." : "";
      setNotice({
        tone: "success",
        message: count ? `Saved ${count} service description(s).${suffix}` : "No service description changes to save.",
      });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "Failed to save service descriptions." });
    },
  });

  const renderMutation = useMutation({
    mutationFn: renderCompose,
    onSuccess: async (response) => {
      setLatestWarnings(response.warnings || []);
      setOutputStale(false);
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      await queryClient.invalidateQueries({ queryKey: ["export-compose"] });
      setPreviewTab("rendered");
      setNotice({ tone: "success", message: "Rendered Stage 2 output." });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "Render failed." });
    },
  });

  const settingsMutation = useMutation({
    mutationFn: saveLlmConfig,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      setSettingsOpen(false);
      setNotice({ tone: "success", message: "LLM settings saved." });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "Failed to save settings." });
    },
  });

  const resetMutation = useMutation({
    mutationFn: resetSession,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      await queryClient.invalidateQueries({ queryKey: ["export-compose"] });
      setComposeName("");
      setLatestWarnings([]);
      setOutputStale(false);
      setPreviewTab("rendered");
      setNotice({ tone: "info", message: "Workspace reset. Import a new compose to continue." });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "Failed to reset workspace." });
    },
  });

  const state = stateQuery.data;
  const renderedYaml = state?.has_stage2 ? exportQuery.data || "" : "";
  const composeText = state?.compose_text || "";

  const handleExport = async () => {
    if (outputStale) {
      setNotice({ tone: "info", message: "Render again to refresh YAML before exporting." });
      return;
    }
    const yaml = renderedYaml || (await exportCompose());
    setPreviewTab("rendered");
    downloadYaml(yaml, composeName || "casaos-compose.yml");
    setNotice({ tone: "success", message: "YAML downloaded." });
  };

  const headerStatus = useMemo(() => {
    if (stateQuery.isLoading) {
      return "Loading session...";
    }
    if (!state?.has_compose) {
      return "No compose loaded";
    }
    if (outputStale) {
      return "Metadata changed. Render again to refresh YAML output";
    }
    return state.has_stage2 ? "Rendered output ready" : "Metadata ready";
  }, [outputStale, state, stateQuery.isLoading]);

  const commandItems = useMemo<CommandPaletteItem[]>(() => {
    if (!state?.has_compose || !state.meta) {
      return [];
    }

    const appFieldLabels: Array<{ target: string; label: string; subtitle: string; keywords: string[] }> = [
      { target: "app.title", label: "App title", subtitle: "Basic info", keywords: ["name", "app"] },
      { target: "app.tagline", label: "App tagline", subtitle: "Basic info", keywords: ["summary"] },
      { target: "app.description", label: "App description", subtitle: "Basic info", keywords: ["details"] },
      { target: "app.author", label: "Author", subtitle: "Basic info", keywords: ["owner"] },
      { target: "app.developer", label: "Developer", subtitle: "Basic info", keywords: [] },
      { target: "app.category", label: "Category", subtitle: "Basic info", keywords: [] },
      { target: "app.version", label: "Version", subtitle: "Version & release", keywords: [] },
      { target: "app.updateAt", label: "Update date", subtitle: "Version & release", keywords: ["release date"] },
      { target: "app.releaseNotes", label: "Release notes", subtitle: "Version & release", keywords: ["changelog"] },
      { target: "app.website", label: "Website", subtitle: "Links & docs", keywords: ["homepage"] },
      { target: "app.repo", label: "Repository", subtitle: "Links & docs", keywords: ["github", "source"] },
      { target: "app.support", label: "Support", subtitle: "Links & docs", keywords: ["issues", "help"] },
      { target: "app.docs", label: "Docs", subtitle: "Links & docs", keywords: ["documentation"] },
      { target: "app.main", label: "Main service", subtitle: "Runtime routing", keywords: [] },
      { target: "app.port_map", label: "Port map", subtitle: "Runtime routing", keywords: ["port"] },
      { target: "app.scheme", label: "Scheme", subtitle: "Runtime routing", keywords: ["http", "https"] },
      { target: "app.index", label: "Index", subtitle: "Runtime routing", keywords: ["launch path"] },
    ];

    const items: CommandPaletteItem[] = [
      {
        id: "action-render",
        label: "Render Stage 2 output",
        subtitle: "Workspace action",
        keywords: ["generate", "yaml", "render"],
        onSelect: () => void renderMutation.mutateAsync(),
      },
      {
        id: "action-export",
        label: "Export YAML",
        subtitle: outputStale ? "Render required before export" : "Workspace action",
        keywords: ["download", "yaml", "export"],
        disabled: outputStale,
        onSelect: () => void handleExport(),
      },
      {
        id: "action-settings",
        label: "Open LLM settings",
        subtitle: "Workspace action",
        keywords: ["model", "api key", "base url"],
        onSelect: () => setSettingsOpen(true),
      },
      {
        id: "action-preview-rendered",
        label: "Show rendered YAML preview",
        subtitle: "Preview tab",
        keywords: ["preview", "yaml"],
        onSelect: () => setPreviewTab("rendered"),
      },
      {
        id: "action-preview-meta",
        label: "Show meta JSON preview",
        subtitle: "Preview tab",
        keywords: ["preview", "meta", "json"],
        onSelect: () => setPreviewTab("meta"),
      },
      {
        id: "action-preview-compose",
        label: "Show source compose preview",
        subtitle: "Preview tab",
        keywords: ["preview", "compose", "source"],
        onSelect: () => setPreviewTab("compose"),
      },
    ];

    for (const field of appFieldLabels) {
      items.push({
        id: field.target,
        label: field.label,
        subtitle: field.subtitle,
        keywords: [field.target, ...field.keywords],
        onSelect: () => setFocusTarget(field.target),
      });
    }

    for (const [serviceName, service] of Object.entries(state.meta.services)) {
      for (const port of service.ports) {
        const target = `service:${serviceName}:port:${port.container}`;
        items.push({
          id: target,
          label: `${serviceName} / port / ${port.container}`,
          subtitle: "Service description",
          keywords: [target, serviceName, port.container, port.description],
          onSelect: () => setFocusTarget(target),
        });
      }
      for (const env of service.envs) {
        const target = `service:${serviceName}:env:${env.container}`;
        items.push({
          id: target,
          label: `${serviceName} / env / ${env.container}`,
          subtitle: "Service description",
          keywords: [target, serviceName, env.container, env.description],
          onSelect: () => setFocusTarget(target),
        });
      }
      for (const volume of service.volumes) {
        const target = `service:${serviceName}:volume:${volume.container}`;
        items.push({
          id: target,
          label: `${serviceName} / volume / ${volume.container}`,
          subtitle: "Service description",
          keywords: [target, serviceName, volume.container, volume.description],
          onSelect: () => setFocusTarget(target),
        });
      }
    }

    return items;
  }, [handleExport, outputStale, renderMutation, setPreviewTab, setSettingsOpen, state]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isMeta = event.metaKey || event.ctrlKey;
      if (!isMeta) {
        return;
      }

      if (event.key.toLowerCase() === "k" && state?.has_compose) {
        event.preventDefault();
        setCommandPaletteOpen(true);
        return;
      }

      if (event.key === "Enter" && state?.has_compose) {
        event.preventDefault();
        void renderMutation.mutateAsync();
        return;
      }

      if (event.shiftKey && event.key.toLowerCase() === "e" && state?.has_compose) {
        event.preventDefault();
        void handleExport();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleExport, renderMutation, state?.has_compose]);

  return (
    <div className="shell">
      <div className="shell__status">{headerStatus}</div>

      {stateQuery.isLoading ? (
        <main className="loadingState">Loading workspace...</main>
      ) : !state?.has_compose ? (
        <LandingView
          loading={importMutation.isPending}
          onImport={async ({ text, name }) => {
            await importMutation.mutateAsync(text);
            setComposeName(name);
          }}
        />
      ) : (
        <WorkspaceView
          state={state}
          composeName={composeName}
          composeText={composeText}
          renderedYaml={renderedYaml}
          warnings={latestWarnings}
          previewTab={previewTab}
          savingApp={saveMutation.isPending}
          savingServices={saveServicesMutation.isPending}
          rendering={renderMutation.isPending}
          exporting={exportQuery.isFetching}
          outputStale={outputStale}
          focusTarget={focusTarget}
          onPreviewTabChange={setPreviewTab}
          onSave={async (values, original) => {
            await saveMutation.mutateAsync({ values, original });
          }}
          onSaveServices={async (changes) => {
            await saveServicesMutation.mutateAsync(changes);
          }}
          onRender={async () => {
            await renderMutation.mutateAsync();
          }}
          onExport={async () => {
            const yaml = renderedYaml || (await exportCompose());
            setPreviewTab("rendered");
            downloadYaml(yaml, composeName || "casaos-compose.yml");
            setNotice({ tone: "success", message: "YAML downloaded." });
          }}
          onReset={async () => {
            await resetMutation.mutateAsync();
          }}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
          onFocusHandled={() => setFocusTarget(null)}
        />
      )}

      {notice ? <div className={`notice notice--${notice.tone}`}>{notice.message}</div> : null}

      <CommandPalette open={commandPaletteOpen} items={commandItems} onClose={() => setCommandPaletteOpen(false)} />

      {state ? (
        <SettingsDialog
          open={settingsOpen}
          llm={state.llm}
          saving={settingsMutation.isPending}
          onClose={() => setSettingsOpen(false)}
          onSubmit={async (values) => {
            await settingsMutation.mutateAsync(values);
          }}
        />
      ) : null}
    </div>
  );
}
