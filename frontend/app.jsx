(() => {
  function bootstrap() {
    const rootNS = window.CasaOSEditor;
    const hasDeps =
      rootNS &&
      rootNS.utils &&
      rootNS.api &&
      rootNS.components &&
      rootNS.steps &&
      rootNS.views &&
      rootNS.components.Button &&
      rootNS.components.Stepper &&
      rootNS.components.ToastHost &&
      rootNS.components.AnimatedContainer &&
      rootNS.steps.StepLoadCompose &&
      rootNS.steps.StepMetadata &&
      rootNS.steps.StepPreview &&
      rootNS.steps.StepExport &&
      rootNS.steps.QuickUpdateCard &&
      rootNS.steps.ExportCard &&
      rootNS.views.LandingView &&
      rootNS.views.FullWorkflowView &&
      rootNS.views.QuickEditView &&
      rootNS.views.SettingsView;

    if (!hasDeps) {
      window.setTimeout(bootstrap, 20);
      return;
    }

    const { useEffect, useMemo, useReducer, useRef } = React;
    const { requestJSON, requestText } = rootNS.api;
    const { cx, uid, readFileAsText, copyToClipboard, clamp } = rootNS.utils;
    const { Button, IconButton, ToastHost, Card, CardHeader, CardBody } = rootNS.components;
    const { LandingView, FullWorkflowView, QuickEditView, SettingsView } = rootNS.views;

    const TOAST_EXIT_MS = 250;

    const initialState = {
      mode: "landing", // "landing" | "full" | "quick" | "settings"
      wizard: {
        stepIndex: 0, // 0-2 (3 steps: Metadata/Preview/Export)
        unlockedIndex: 0,
      },
      compose: {
        mode: "upload",
        text: "",
        file: null,
      },
      params: {
        useLLM: true,
        useParams: true,
        autoRenderAfterSave: true,
        file: null,
        dirty: false,
        draft: {
          store_folder: "",
          author: "",
          developer: "",
          title: "",
          tagline: "",
          description: "",
          category: "",
          main: "",
          port_map: "",
          scheme: "",
          index: "",
        },
      },
      llm: {
        dirty: false,
        draft: {
          base_url: "",
          api_key: "",
          model: "gpt-4.1-mini",
          temperature: 0.2,
          prompt_template: "",
        },
      },
      preview: {
        tab: "compose",
      },
      renderedYaml: "",
      engine: {
        languages: [],
        has_compose: false,
        has_meta: false,
        has_stage2: false,
        meta: null,
        llm: {},
        lastSyncedAt: null,
      },
      busy: {
        syncing: false,
        loadingCompose: false,
        fillingMeta: false,
        savingLLM: false,
        rendering: false,
        exporting: false,
        patchingField: false,
      },
      dialogs: {
        postLoadChooserOpen: false,
        postLoadHasStage2: false,
      },
      toasts: [],
    };

    function reducer(state, action) {
      switch (action.type) {
        case "SET_MODE": {
          return {
            ...state,
            mode: action.mode,
            wizard: { ...state.wizard, stepIndex: 0 },
            dialogs: { ...state.dialogs, postLoadChooserOpen: false },
          };
        }
        case "SET_STEP": {
          const clamped = Math.max(0, Math.min(2, action.stepIndex));
          return { ...state, wizard: { ...state.wizard, stepIndex: clamped } };
        }
        case "UNLOCK_STEP": {
          return {
            ...state,
            wizard: { ...state.wizard, unlockedIndex: Math.max(state.wizard.unlockedIndex, Math.min(2, action.index)) },
          };
        }
        case "SET_COMPOSE_MODE": {
          return { ...state, compose: { ...state.compose, mode: action.mode } };
        }
        case "SET_COMPOSE_TEXT": {
          return { ...state, compose: { ...state.compose, text: action.text } };
        }
        case "SET_COMPOSE_FILE": {
          return { ...state, compose: { ...state.compose, file: action.file || null } };
        }
        case "SET_PARAMS_FILE": {
          return { ...state, params: { ...state.params, file: action.file || null } };
        }
        case "SET_PARAMS_MODE": {
          return { ...state, params: { ...state.params, [action.key]: Boolean(action.value) } };
        }
        case "SET_PARAMS_DRAFT_FIELD": {
          return {
            ...state,
            params: {
              ...state.params,
              dirty: true,
              draft: { ...state.params.draft, [action.field]: action.value },
            },
          };
        }
        case "SET_LLM_DRAFT_FIELD": {
          return {
            ...state,
            llm: {
              ...state.llm,
              dirty: true,
              draft: { ...state.llm.draft, [action.field]: action.value },
            },
          };
        }
        case "SET_PREVIEW_TAB": {
          return { ...state, preview: { ...state.preview, tab: action.tab } };
        }
        case "SET_RENDERED_YAML": {
          return { ...state, renderedYaml: action.value };
        }
        case "SET_ENGINE": {
          const nextEngine = { ...state.engine, ...action.engine, lastSyncedAt: action.lastSyncedAt };
          let nextUnlocked = state.wizard.unlockedIndex;
          if (!nextEngine.has_compose) {
            nextUnlocked = 0;
          } else if (nextEngine.has_stage2) {
            nextUnlocked = Math.max(nextUnlocked, 2);
          } else {
            nextUnlocked = Math.max(nextUnlocked, 0);
          }

          const nextState = {
            ...state,
            engine: nextEngine,
            wizard: { ...state.wizard, unlockedIndex: nextUnlocked },
          };

          if (!state.llm.dirty && action.engine?.llm) {
            nextState.llm = {
              ...nextState.llm,
              draft: {
                ...nextState.llm.draft,
                base_url: action.engine.llm?.stage1?.base_url || action.engine.llm.base_url || "",
                model: action.engine.llm?.stage1?.model || action.engine.llm.model || nextState.llm.draft.model,
                temperature:
                  typeof action.engine.llm?.stage1?.temperature === "number"
                    ? action.engine.llm.stage1.temperature
                    : typeof action.engine.llm?.temperature === "number"
                      ? action.engine.llm.temperature
                      : nextState.llm.draft.temperature,
              },
            };
          }

          if (!state.params.dirty && action.engine?.meta?.app) {
            const app = action.engine.meta.app;
            nextState.params = {
              ...nextState.params,
              draft: {
                ...nextState.params.draft,
                author: app.author || nextState.params.draft.author,
                developer: app.developer || nextState.params.draft.developer,
                title: app.title || nextState.params.draft.title,
                tagline: app.tagline || nextState.params.draft.tagline,
                description: app.description || nextState.params.draft.description,
                category: app.category || nextState.params.draft.category,
                main: app.main || nextState.params.draft.main,
                port_map: app.port_map || nextState.params.draft.port_map,
                scheme: app.scheme || nextState.params.draft.scheme,
                index: app.index || nextState.params.draft.index,
              },
            };
          }

          return nextState;
        }
        case "SET_BUSY": {
          return { ...state, busy: { ...state.busy, [action.key]: Boolean(action.value) } };
        }
        case "PUSH_TOAST": {
          return { ...state, toasts: [...state.toasts, action.toast] };
        }
        case "SET_TOAST_EXITING": {
          return {
            ...state,
            toasts: state.toasts.map((t) => (t.id === action.id ? { ...t, exiting: true } : t)),
          };
        }
        case "DISMISS_TOAST": {
          return { ...state, toasts: state.toasts.filter((item) => item.id !== action.id) };
        }
        case "RESET_FOR_NEW_COMPOSE": {
          return {
            ...state,
            mode: "landing",
            preview: { tab: "compose" },
            renderedYaml: "",
            dialogs: { ...state.dialogs, postLoadChooserOpen: false },
            wizard: { stepIndex: 0, unlockedIndex: 0 },
          };
        }
        case "OPEN_POST_LOAD_CHOOSER": {
          return {
            ...state,
            dialogs: {
              ...state.dialogs,
              postLoadChooserOpen: true,
              postLoadHasStage2: Boolean(action.hasStage2),
            },
          };
        }
        case "CLOSE_POST_LOAD_CHOOSER": {
          return { ...state, dialogs: { ...state.dialogs, postLoadChooserOpen: false } };
        }
        default:
          return state;
      }
    }

    function App() {
      const [state, dispatch] = useReducer(reducer, initialState);
      const firstSyncRef = useRef(true);
      const toastTimersRef = useRef(new Map());

      const pushToast = (toast) => {
        const id = toast.id || uid("toast");
        dispatch({
          type: "PUSH_TOAST",
          toast: {
            id,
            title: toast.title || "",
            message: toast.message || "",
            variant: toast.variant || "info",
            exiting: false,
          },
        });
        const duration = clamp(toast.duration ?? 4500, 1500, 15000);
        if (toastTimersRef.current.has(id)) {
          window.clearTimeout(toastTimersRef.current.get(id));
        }
        toastTimersRef.current.set(
          id,
          window.setTimeout(() => {
            dismissToast(id);
          }, duration)
        );
      };

      const dismissToast = (id) => {
        // Start exit animation
        dispatch({ type: "SET_TOAST_EXITING", id });
        const timer = toastTimersRef.current.get(id);
        if (timer) {
          window.clearTimeout(timer);
        }
        // After exit animation completes, remove from DOM
        toastTimersRef.current.set(
          id,
          window.setTimeout(() => {
            dispatch({ type: "DISMISS_TOAST", id });
            toastTimersRef.current.delete(id);
          }, TOAST_EXIT_MS)
        );
      };

      const syncUIState = async ({ silent = false } = {}) => {
        dispatch({ type: "SET_BUSY", key: "syncing", value: true });
        try {
          const data = await requestJSON("/api/state");
          dispatch({ type: "SET_ENGINE", engine: data, lastSyncedAt: Date.now() });
          if (!silent) {
            pushToast({ title: "Synced", message: "UI state refreshed from server.", variant: "info", duration: 2200 });
          }
          return data;
        } catch (error) {
          if (!silent) {
            pushToast({ title: "Sync failed", message: error.message, variant: "danger" });
          }
          return null;
        } finally {
          dispatch({ type: "SET_BUSY", key: "syncing", value: false });
        }
      };

      useEffect(() => {
        syncUIState({ silent: true });
      }, []);

      // First sync: auto-detect mode
      useEffect(() => {
        if (!firstSyncRef.current) return;
        if (state.engine.lastSyncedAt == null) return;
        firstSyncRef.current = false;

        if (state.engine.has_stage2) {
          dispatch({ type: "SET_MODE", mode: "quick" });
          return;
        }
        if (state.engine.has_compose) {
          dispatch({ type: "OPEN_POST_LOAD_CHOOSER", hasStage2: false });
        }
      }, [state.engine.has_compose, state.engine.has_stage2, state.engine.lastSyncedAt]);

      // Auto-refresh export when entering export step in full mode
      useEffect(() => {
        if (state.mode !== "full") return;
        const canExport = state.engine.has_compose && (state.engine.has_meta || state.engine.has_stage2);
        if (
          state.wizard.stepIndex === 2 &&
          canExport &&
          !state.busy.exporting &&
          !String(state.renderedYaml || "").trim()
        ) {
          refreshExportYaml();
        }
      }, [state.mode, state.wizard.stepIndex, state.engine.has_compose, state.engine.has_meta, state.engine.has_stage2]);

      // Auto-refresh export when entering quick mode
      useEffect(() => {
        if (state.mode !== "quick") return;
        const canExport = state.engine.has_compose && (state.engine.has_meta || state.engine.has_stage2);
        if (canExport && !state.busy.exporting && !String(state.renderedYaml || "").trim()) {
          refreshExportYaml();
        }
      }, [state.mode]);

      useEffect(
        () => () => {
          for (const timer of toastTimersRef.current.values()) {
            window.clearTimeout(timer);
          }
          toastTimersRef.current.clear();
        },
        []
      );

      const buildParamsPayload = () => ({
        app: {
          store_folder: String(state.params.draft.store_folder || "").trim(),
          author: String(state.params.draft.author || "").trim(),
          developer: String(state.params.draft.developer || "").trim(),
          title: String(state.params.draft.title || "").trim(),
          tagline: String(state.params.draft.tagline || "").trim(),
          description: String(state.params.draft.description || "").trim(),
          category: String(state.params.draft.category || "").trim(),
          main: String(state.params.draft.main || "").trim(),
          port_map: String(state.params.draft.port_map || "").trim(),
          scheme: String(state.params.draft.scheme || "").trim(),
          index: String(state.params.draft.index || "").trim(),
        },
      });

      const loadComposeFromFile = async () => {
        const file = state.compose.file;
        if (!file) {
          pushToast({ title: "No file selected", message: "Choose a .yml/.yaml file first.", variant: "warning" });
          return;
        }
        dispatch({ type: "SET_BUSY", key: "loadingCompose", value: true });
        try {
          const text = await readFileAsText(file);
          dispatch({ type: "SET_COMPOSE_TEXT", text });
          const formData = new FormData();
          formData.append("file", file);
          await requestJSON("/api/compose", { method: "POST", body: formData });
          firstSyncRef.current = false;
          const data = await syncUIState({ silent: true });
          dispatch({ type: "RESET_FOR_NEW_COMPOSE" });
          dispatch({ type: "OPEN_POST_LOAD_CHOOSER", hasStage2: Boolean(data?.has_stage2) });
          pushToast({
            title: "Compose loaded",
            message: "Choose a workflow: full flow or quick update.",
            variant: "success",
            duration: 4200,
          });
        } catch (error) {
          pushToast({ title: "Load failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "loadingCompose", value: false });
        }
      };

      const loadComposeFromText = async () => {
        const text = state.compose.text;
        if (!String(text || "").trim()) {
          pushToast({ title: "Empty content", message: "Paste compose YAML first.", variant: "warning" });
          return;
        }
        dispatch({ type: "SET_BUSY", key: "loadingCompose", value: true });
        try {
          await requestJSON("/api/compose-text", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          });
          firstSyncRef.current = false;
          const data = await syncUIState({ silent: true });
          dispatch({ type: "RESET_FOR_NEW_COMPOSE" });
          dispatch({ type: "OPEN_POST_LOAD_CHOOSER", hasStage2: Boolean(data?.has_stage2) });
          pushToast({
            title: "Compose loaded",
            message: "Choose a workflow: full flow or quick update.",
            variant: "success",
            duration: 4200,
          });
        } catch (error) {
          pushToast({ title: "Load failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "loadingCompose", value: false });
        }
      };

      const saveLLMSettings = async () => {
        dispatch({ type: "SET_BUSY", key: "savingLLM", value: true });
        try {
          const formData = new FormData();
          formData.append("stage", "stage1");
          formData.append("base_url", state.llm.draft.base_url || "");
          if (String(state.llm.draft.api_key || "").trim()) {
            formData.append("api_key", state.llm.draft.api_key.trim());
          }
          formData.append("model", state.llm.draft.model || "gpt-4.1-mini");
          formData.append("temperature", String(state.llm.draft.temperature ?? 0.2));
          await requestJSON("/api/llm", { method: "POST", body: formData });
          await syncUIState({ silent: true });
          pushToast({ title: "Saved", message: "Stage 1 LLM settings updated.", variant: "success" });
        } catch (error) {
          pushToast({ title: "LLM save failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "savingLLM", value: false });
        }
      };

      const appendLLMRequestFields = (formData) => {
        formData.append("model", state.llm.draft.model || "gpt-4.1-mini");
        formData.append("temperature", String(state.llm.draft.temperature ?? 0.2));
        if (String(state.llm.draft.base_url || "").trim()) {
          formData.append("llm_base_url", state.llm.draft.base_url.trim());
        }
        if (String(state.llm.draft.api_key || "").trim()) {
          formData.append("llm_api_key", state.llm.draft.api_key.trim());
        }
      };

      const renderStage2 = async ({ focusTab = true } = {}) => {
        dispatch({ type: "SET_BUSY", key: "rendering", value: true });
        try {
          const formData = new FormData();
          const renderResult = await requestJSON("/api/render", { method: "POST", body: formData });
          const yamlText = await requestText("/api/export", { method: "POST" });
          dispatch({ type: "SET_RENDERED_YAML", value: yamlText });
          if (focusTab) {
            dispatch({ type: "SET_PREVIEW_TAB", tab: "rendered" });
          }
          await syncUIState({ silent: true });
          dispatch({ type: "UNLOCK_STEP", index: 2 });
          const warnings = Array.isArray(renderResult?.warnings) ? renderResult.warnings : [];
          if (warnings.length) {
            pushToast({ title: "Rendered (degraded)", message: warnings[0], variant: "warning", duration: 5200 });
          } else {
            pushToast({ title: "Rendered", message: "x-casaos output is ready.", variant: "success" });
          }
        } catch (error) {
          pushToast({ title: "Render failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "rendering", value: false });
        }
      };

      const fillMetadata = async () => {
        if (!state.engine.has_compose) {
          pushToast({ title: "No compose", message: "Load a compose file first.", variant: "warning" });
          return;
        }
        if (!state.params.useLLM && !state.params.useParams) {
          pushToast({ title: "Select a mode", message: "Enable Params and/or LLM.", variant: "warning" });
          return;
        }
        dispatch({ type: "SET_BUSY", key: "fillingMeta", value: true });
        const shouldAutoRender = Boolean(state.params.autoRenderAfterSave);
        try {
          const formData = new FormData();
          formData.append("use_llm", state.params.useLLM ? "true" : "false");
          formData.append("use_params", state.params.useParams ? "true" : "false");

          if (state.params.useLLM) {
            appendLLMRequestFields(formData);
          }

          if (state.params.useParams) {
            if (state.params.file) {
              formData.append("params_file", state.params.file);
            } else {
              formData.append("params_json", JSON.stringify(buildParamsPayload()));
            }
          }

          const result = await requestJSON("/api/meta/fill", { method: "POST", body: formData });
          await syncUIState({ silent: true });
          dispatch({ type: "SET_RENDERED_YAML", value: "" });
          const warnings = Array.isArray(result?.warnings) ? result.warnings : [];
          if (warnings.length) {
            pushToast({ title: "Metadata saved (LLM skipped)", message: warnings[0], variant: "warning", duration: 6500 });
          } else {
            pushToast({
              title: "Metadata saved",
              message: shouldAutoRender ? "Metadata updated. Rendering x-casaos in background." : "Metadata updated successfully.",
              variant: "success",
            });
          }
        } catch (error) {
          pushToast({ title: "Metadata failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "fillingMeta", value: false });
        }
        if (shouldAutoRender) {
          void renderStage2({ focusTab: false });
        }
      };

      const refreshExportYaml = async () => {
        dispatch({ type: "SET_BUSY", key: "exporting", value: true });
        try {
          const yamlText = await requestText("/api/export", { method: "POST" });
          dispatch({ type: "SET_RENDERED_YAML", value: yamlText });
          await syncUIState({ silent: true });
          pushToast({ title: "YAML refreshed", message: "Export updated from server.", variant: "success", duration: 2500 });
        } catch (error) {
          pushToast({ title: "Export failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "exporting", value: false });
        }
      };

      const quickUpdateField = async ({ target, value, multilang, language }) => {
        const targetValue = String(target || "").trim();
        if (!state.engine.has_compose) {
          pushToast({ title: "Not ready", message: "Load a compose file first.", variant: "warning" });
          return false;
        }
        if (!targetValue) {
          pushToast({ title: "Missing target", message: "Enter a field target like app.description.", variant: "warning" });
          return false;
        }

        const isMultilang = Boolean(multilang);
        const languageValue = String(language || "").trim();
        if (isMultilang) {
          const languages = Array.isArray(state.engine.languages) ? state.engine.languages : [];
          if (languageValue && languages.length && !languages.includes(languageValue)) {
            pushToast({
              title: "Unknown language",
              message: `Language '${languageValue}' is not in the server language list.`,
              variant: "warning",
            });
            return false;
          }
        }
        dispatch({ type: "SET_BUSY", key: "patchingField", value: true });
        try {
          const nextValue = String(value ?? "");

          const utils = rootNS.utils || {};
          const APP_MULTILANG_FIELDS = utils.APP_MULTILANG_FIELDS || new Set();
          const APP_SINGLE_FIELDS = utils.APP_SINGLE_FIELDS || new Set();
          const SERVICE_FIELD_TYPES = utils.SERVICE_FIELD_TYPES || new Set();

          const targetParts = targetValue.split(":");
          const isAppTarget = targetValue.startsWith("app.");
          const isServiceMultilangTarget =
            targetParts.length >= 4 &&
            targetParts[0] === "service" &&
            SERVICE_FIELD_TYPES.has(targetParts[2]);
          const isServiceSingleTarget = targetParts.length >= 3 && targetParts[0] === "service" && !isServiceMultilangTarget;

          const appFieldPath = isAppTarget ? targetValue.slice("app.".length) : "";
          const isAppMultilangTarget = isAppTarget && (APP_MULTILANG_FIELDS.has(appFieldPath) || appFieldPath.startsWith("tips."));
          const isAppSingleTarget = isAppTarget && APP_SINGLE_FIELDS.has(appFieldPath);

          if (isAppMultilangTarget && !isMultilang) {
            pushToast({ title: "Wrong mode", message: "This app target is multi-language. Turn on multi-language mode.", variant: "warning" });
            return false;
          }
          if (isAppSingleTarget && isMultilang) {
            pushToast({ title: "Wrong mode", message: "This app target is single-language. Turn off multi-language mode.", variant: "warning" });
            return false;
          }
          if (isServiceMultilangTarget && !isMultilang) {
            pushToast({ title: "Wrong mode", message: "This service target requires multi-language mode.", variant: "warning" });
            return false;
          }
          if (isServiceSingleTarget && isMultilang) {
            pushToast({ title: "Wrong mode", message: "This service target is single-language. Turn off multi-language mode.", variant: "warning" });
            return false;
          }
          if (!isAppTarget && !targetValue.startsWith("service:")) {
            pushToast({ title: "Invalid target", message: "Target must start with app. or service:.", variant: "warning" });
            return false;
          }

          const shouldUpdateMeta =
            Boolean(state.engine.has_meta) &&
            ((isAppTarget && (utils.APP_META_UPDATABLE_FIELDS || new Set()).has(appFieldPath)) || isServiceMultilangTarget);
          const shouldUpdateMetaValue = shouldUpdateMeta && !isMultilang;

          if (shouldUpdateMetaValue) {
            await requestJSON("/api/meta/update", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                target: targetValue,
                value: nextValue,
                propagate_all_languages: false,
                sync_stage2: false,
              }),
            });
          }

          let stage2Warnings = [];
          if (isMultilang) {
            const updateResult = await requestJSON("/api/stage2/update-multi", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                target: targetValue,
                value: nextValue,
                overwrite_all_languages: true,
                language: languageValue || undefined,
              }),
            });
            stage2Warnings = Array.isArray(updateResult?.warnings) ? updateResult.warnings : [];
          } else {
            await requestJSON("/api/stage2/update-single", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ target: targetValue, value: nextValue }),
            });
          }

          const yamlText = await requestText("/api/export", { method: "POST" });
          dispatch({ type: "SET_RENDERED_YAML", value: yamlText });
          await syncUIState({ silent: true });
          pushToast({
            title: "Updated",
            message: isMultilang
              ? stage2Warnings.length
                ? `Updated ${targetValue} (copied to all locales; LLM unavailable).`
                : `Updated ${targetValue} (LLM translated).`
              : `Updated ${targetValue}.`,
            variant: stage2Warnings.length ? "warning" : "success",
            duration: 2500,
          });
          return true;
        } catch (error) {
          pushToast({ title: "Update failed", message: error.message, variant: "danger" });
          return false;
        } finally {
          dispatch({ type: "SET_BUSY", key: "patchingField", value: false });
        }
      };

      const downloadYaml = () => {
        const text = state.renderedYaml;
        if (!text.trim()) {
          pushToast({ title: "Nothing to download", message: "Export YAML first.", variant: "warning" });
          return;
        }
        const blob = new Blob([text], { type: "text/yaml;charset=utf-8" });
        const url = window.URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = "casaos-compose.yml";
        anchor.click();
        window.URL.revokeObjectURL(url);
      };

      const copyYaml = async () => {
        const ok = await copyToClipboard(state.renderedYaml);
        pushToast({
          title: ok ? "Copied" : "Copy failed",
          message: ok ? "YAML copied to clipboard." : "Browser refused clipboard access.",
          variant: ok ? "success" : "danger",
          duration: 2500,
        });
      };

      // Navigation
      const maxEnabledIndex = state.wizard.unlockedIndex;

      const canContinue = state.engine.has_compose;

      const onBack = () => {
        if (state.wizard.stepIndex === 0) {
          dispatch({ type: "SET_MODE", mode: "landing" });
          return;
        }
        dispatch({ type: "SET_STEP", stepIndex: state.wizard.stepIndex - 1 });
      };

      const onContinue = () => {
        const next = Math.min(2, state.wizard.stepIndex + 1);
        dispatch({ type: "UNLOCK_STEP", index: next });
        dispatch({ type: "SET_STEP", stepIndex: next });
        if (next === 2 && state.engine.has_compose && !state.renderedYaml.trim()) {
          refreshExportYaml();
        }
      };

      const chooseFullWorkflow = () => {
        dispatch({ type: "SET_MODE", mode: "full" });
      };

      const chooseQuickUpdate = () => {
        dispatch({ type: "SET_MODE", mode: "quick" });
      };

      const backToLanding = () => {
        dispatch({ type: "SET_MODE", mode: "landing" });
      };

      // Dialogs
      const postLoadHasStage2 = Boolean(state.dialogs?.postLoadHasStage2);
      const showPostLoadChooser = Boolean(state.dialogs?.postLoadChooserOpen);

      // Header
      const headerSubtitle =
        state.mode === "quick" ? "Quick edit mode — patch fields and export."
          : state.mode === "full" ? "Full workflow — metadata, preview, export."
            : state.engine.has_compose ? "Compose loaded. Choose a workflow."
              : "Load a docker-compose.yml to begin.";

      const modePillLabel =
        state.mode === "full" ? "Full Workflow"
          : state.mode === "quick" ? "Quick Edit"
            : state.mode === "settings" ? "Settings"
              : "Wizard";

      const SettingsIcon = () => (
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      );

      return (
        <div className="app-layout">
          <header className="top-bar">
            <div className="top-bar__left">
              <div className="logo" onClick={backToLanding} style={{ cursor: 'pointer' }}>
                <div className="logo__icon">C</div>
                <div className="logo__text">Studio</div>
              </div>
            </div>

            <div className="top-bar__center">
              {state.mode === "full" && (
                <div className="horizontal-stepper">
                  {[
                    { idx: 0, label: "Metadata" },
                    { idx: 1, label: "Preview" },
                    { idx: 2, label: "Export" }
                  ].map(step => (
                    <button
                      key={step.idx}
                      className={cx("h-step", {
                        "h-step--active": state.wizard.stepIndex === step.idx,
                        "h-step--locked": step.idx > state.wizard.unlockedIndex
                      })}
                      disabled={step.idx > state.wizard.unlockedIndex}
                      onClick={() => dispatch({ type: "SET_STEP", stepIndex: step.idx })}
                    >
                      <span className="h-step__num">{step.idx + 1}</span>
                      <span className="h-step__label">{step.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="top-bar__right">
              <IconButton label="Settings" onClick={() => dispatch({ type: "SET_MODE", mode: "settings" })}>
                <SettingsIcon />
              </IconButton>
              <IconButton label="Sync" loading={state.busy.syncing} onClick={() => syncUIState()}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path d="M21 2v6h-6M3 22v-6h6M21 13a9 9 0 11-3-7.7L21 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </IconButton>
            </div>
          </header>

          <main className="content-area">
            <div className="view-scroll-box">
              <div className="view-container">
                {state.mode === "landing" && (
                  <LandingView
                    mode={state.compose.mode}
                    onModeChange={(m) => dispatch({ type: "SET_COMPOSE_MODE", mode: m })}
                    composeText={state.compose.text}
                    composeFile={state.compose.file}
                    onComposeTextChange={(t) => dispatch({ type: "SET_COMPOSE_TEXT", text: t })}
                    onComposeFileChange={(f) => dispatch({ type: "SET_COMPOSE_FILE", file: f })}
                    onLoadFromFile={loadComposeFromFile}
                    onLoadFromText={loadComposeFromText}
                    engine={state.engine}
                    busy={state.busy.loadingCompose}
                  />
                )}

                {state.mode === "full" && (
                  <FullWorkflowView
                    state={state}
                    dispatch={dispatch}
                    stepIndex={state.wizard.stepIndex}
                    maxEnabledIndex={state.wizard.unlockedIndex}
                    onStepChange={(idx) => dispatch({ type: "SET_STEP", stepIndex: idx })}
                    saveLLMSettings={saveLLMSettings}
                    fillMetadata={fillMetadata}
                    renderStage2={renderStage2}
                    refreshExportYaml={refreshExportYaml}
                    downloadYaml={downloadYaml}
                    copyYaml={copyYaml}
                    onBack={onBack}
                    onContinue={onContinue}
                    canContinue={canContinue}
                  />
                )}

                {state.mode === "quick" && (
                  <QuickEditView
                    engine={state.engine}
                    renderedYaml={state.renderedYaml}
                    onQuickUpdate={quickUpdateField}
                    downloadYaml={downloadYaml}
                    copyYaml={copyYaml}
                    onRefresh={refreshExportYaml}
                    busy={state.busy}
                    backToLanding={backToLanding}
                  />
                )}

                {state.mode === "settings" && (
                  <SettingsView
                    llm={state.llm.draft}
                    onFieldChange={(field, value) => dispatch({ type: "SET_LLM_DRAFT_FIELD", field, value })}
                    onSave={saveLLMSettings}
                    onBack={backToLanding}
                    busy={state.busy.savingLLM}
                  />
                )}
              </div>
            </div>
          </main>

          <ToastHost toasts={state.toasts} onDismiss={dismissToast} />

          {showPostLoadChooser && (
            <div className="modal-overlay">
              <Card className="modal-card">
                <CardHeader title="Choose Workflow" subtitle="Your compose file is loaded. Select your path." />
                <CardBody>
                  <div className="grid2">
                    <button className="choice-box" onClick={chooseFullWorkflow}>
                      <div className="choice-box__icon">🚀</div>
                      <div className="choice-box__title">Full Workflow</div>
                      <div className="choice-box__desc">Step-by-step metadata & preview.</div>
                    </button>
                    <button className="choice-box" onClick={chooseQuickUpdate}>
                      <div className="choice-box__icon">⚡</div>
                      <div className="choice-box__title">Quick Edit</div>
                      <div className="choice-box__desc">Direct field patching.</div>
                    </button>
                  </div>
                </CardBody>
              </Card>
            </div>
          )}
        </div>
      );
    }

    const container = document.getElementById("root");
    const reactRoot = ReactDOM.createRoot(container);
    reactRoot.render(<App />);
  }

  bootstrap();
})();
