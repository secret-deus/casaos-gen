(() => {
  function bootstrap() {
    const rootNS = window.CasaOSEditor;
    const hasDeps =
      rootNS &&
      rootNS.utils &&
      rootNS.api &&
      rootNS.components &&
      rootNS.steps &&
      rootNS.components.Button &&
      rootNS.components.Stepper &&
      rootNS.components.ToastHost &&
      rootNS.steps.StepLoadCompose &&
      rootNS.steps.StepMetadata &&
      rootNS.steps.StepPreview &&
      rootNS.steps.StepExport;

    if (!hasDeps) {
      window.setTimeout(bootstrap, 20);
      return;
    }

    const { useEffect, useMemo, useReducer, useRef } = React;
    const { requestJSON, requestText } = rootNS.api;
    const { cx, uid, readFileAsText, copyToClipboard, clamp } = rootNS.utils;
    const { Button, IconButton, Stepper, ToastHost, Card, CardHeader, CardBody } = rootNS.components;
    const { StepLoadCompose, StepMetadata, StepPreview, StepExport } = rootNS.steps;

    const STEPS = [
      { key: "load", label: "Load Compose" },
      { key: "metadata", label: "Metadata" },
      { key: "preview", label: "Preview" },
      { key: "export", label: "Export" },
    ];

    const initialState = {
      wizard: {
        stepIndex: 0,
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
        case "SET_STEP": {
          return { ...state, wizard: { ...state.wizard, stepIndex: action.stepIndex } };
        }
        case "UNLOCK_STEP": {
          return {
            ...state,
            wizard: { ...state.wizard, unlockedIndex: Math.max(state.wizard.unlockedIndex, action.index) },
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
              draft: {
                ...state.params.draft,
                [action.field]: action.value,
              },
            },
          };
        }
        case "SET_LLM_DRAFT_FIELD": {
          return {
            ...state,
            llm: {
              ...state.llm,
              dirty: true,
              draft: {
                ...state.llm.draft,
                [action.field]: action.value,
              },
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
            nextUnlocked = Math.max(nextUnlocked, 3);
          } else {
            nextUnlocked = Math.max(nextUnlocked, 1);
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
                base_url: action.engine.llm.base_url || "",
                model: action.engine.llm.model || nextState.llm.draft.model,
                temperature:
                  typeof action.engine.llm.temperature === "number"
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
        case "DISMISS_TOAST": {
          return { ...state, toasts: state.toasts.filter((item) => item.id !== action.id) };
        }
        case "RESET_FOR_NEW_COMPOSE": {
          const requestedStepIndex = typeof action.stepIndex === "number" ? action.stepIndex : 1;
          const requestedUnlockedIndex =
            typeof action.unlockedIndex === "number" ? action.unlockedIndex : requestedStepIndex;

          const safeStepIndex = Math.max(0, Math.min(3, requestedStepIndex));
          const safeUnlockedIndex = Math.max(safeStepIndex, Math.max(0, Math.min(3, requestedUnlockedIndex)));
          return {
            ...state,
            preview: { tab: "compose" },
            renderedYaml: "",
            dialogs: { ...state.dialogs, postLoadChooserOpen: false },
            wizard: { stepIndex: safeStepIndex, unlockedIndex: safeUnlockedIndex },
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

      const engineMaxIndex = useMemo(() => {
        if (!state.engine.has_compose) {
          return 0;
        }
        return 3;
      }, [state.engine.has_compose, state.engine.has_stage2]);

      const maxEnabledIndex = Math.min(engineMaxIndex, state.wizard.unlockedIndex);

      const pushToast = (toast) => {
        const id = toast.id || uid("toast");
        dispatch({
          type: "PUSH_TOAST",
          toast: {
            id,
            title: toast.title || "",
            message: toast.message || "",
            variant: toast.variant || "info",
          },
        });
        const duration = clamp(toast.duration ?? 4500, 1500, 15000);
        if (toastTimersRef.current.has(id)) {
          window.clearTimeout(toastTimersRef.current.get(id));
        }
        toastTimersRef.current.set(
          id,
          window.setTimeout(() => {
            dispatch({ type: "DISMISS_TOAST", id });
            toastTimersRef.current.delete(id);
          }, duration)
        );
      };

      const dismissToast = (id) => {
        dispatch({ type: "DISMISS_TOAST", id });
        const timer = toastTimersRef.current.get(id);
        if (timer) {
          window.clearTimeout(timer);
          toastTimersRef.current.delete(id);
        }
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

      useEffect(() => {
        // Keep UI in sync even if server state changes outside the current step.
        syncUIState({ silent: true });
      }, [state.wizard.stepIndex]);

      useEffect(() => {
        if (!firstSyncRef.current) {
          return;
        }
        if (state.engine.lastSyncedAt == null) {
          return;
        }
        firstSyncRef.current = false;

        if (state.engine.has_stage2) {
          dispatch({ type: "UNLOCK_STEP", index: 3 });
          dispatch({ type: "SET_STEP", stepIndex: 3 });
          return;
        }
        if (state.engine.has_compose) {
          dispatch({ type: "UNLOCK_STEP", index: 1 });
          dispatch({ type: "SET_STEP", stepIndex: 1 });
        }
      }, [state.engine.has_compose, state.engine.has_stage2, state.engine.lastSyncedAt]);

      useEffect(() => {
        if (!state.engine.has_compose && state.wizard.stepIndex !== 0) {
          dispatch({ type: "SET_STEP", stepIndex: 0 });
        }
        if (state.wizard.stepIndex > maxEnabledIndex) {
          dispatch({ type: "SET_STEP", stepIndex: maxEnabledIndex });
        }
      }, [state.engine.has_compose, maxEnabledIndex, state.wizard.stepIndex]);

      useEffect(() => {
        const canExport = state.engine.has_compose && (state.engine.has_meta || state.engine.has_stage2);
        if (
          state.wizard.stepIndex === 3 &&
          canExport &&
          !state.busy.exporting &&
          !String(state.renderedYaml || "").trim()
        ) {
          refreshExportYaml();
        }
      }, [state.wizard.stepIndex, state.engine.has_compose, state.engine.has_meta, state.engine.has_stage2]);

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
          description: state.params.draft.description || "",
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
          dispatch({
            type: "RESET_FOR_NEW_COMPOSE",
            stepIndex: 1,
            unlockedIndex: 3,
          });
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
          dispatch({
            type: "RESET_FOR_NEW_COMPOSE",
            stepIndex: 1,
            unlockedIndex: 3,
          });
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
          formData.append("base_url", state.llm.draft.base_url || "");
          if (String(state.llm.draft.api_key || "").trim()) {
            formData.append("api_key", state.llm.draft.api_key.trim());
          }
          formData.append("model", state.llm.draft.model || "gpt-4.1-mini");
          formData.append("temperature", String(state.llm.draft.temperature ?? 0.2));
          await requestJSON("/api/llm", { method: "POST", body: formData });
          await syncUIState({ silent: true });
          pushToast({ title: "Saved", message: "LLM settings updated.", variant: "success" });
        } catch (error) {
          pushToast({ title: "LLM save failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "savingLLM", value: false });
        }
      };

      const renderStage2 = async ({ focusTab = true } = {}) => {
        dispatch({ type: "SET_BUSY", key: "rendering", value: true });
        try {
          await requestJSON("/api/render", { method: "POST" });
          const yamlText = await requestText("/api/export", { method: "POST" });
          dispatch({ type: "SET_RENDERED_YAML", value: yamlText });
          if (focusTab) {
            dispatch({ type: "SET_PREVIEW_TAB", tab: "rendered" });
          }
          await syncUIState({ silent: true });
          dispatch({ type: "UNLOCK_STEP", index: 3 });
          pushToast({ title: "Rendered", message: "x-casaos output is ready.", variant: "success" });
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
        try {
          const formData = new FormData();
          formData.append("use_llm", state.params.useLLM ? "true" : "false");
          formData.append("use_params", state.params.useParams ? "true" : "false");

          if (state.params.useLLM) {
            formData.append("model", state.llm.draft.model || "gpt-4.1-mini");
            formData.append("temperature", String(state.llm.draft.temperature ?? 0.2));
            if (String(state.llm.draft.base_url || "").trim()) {
              formData.append("llm_base_url", state.llm.draft.base_url.trim());
            }
            if (String(state.llm.draft.api_key || "").trim()) {
              formData.append("llm_api_key", state.llm.draft.api_key.trim());
            }
          }

          if (state.params.useParams) {
            if (state.params.file) {
              formData.append("params_file", state.params.file);
            } else {
              formData.append("params_json", JSON.stringify(buildParamsPayload()));
            }
          }

          await requestJSON("/api/meta/fill", { method: "POST", body: formData });
          await syncUIState({ silent: true });
          dispatch({ type: "SET_RENDERED_YAML", value: "" });
          pushToast({ title: "Metadata saved", message: "Metadata updated successfully.", variant: "success" });

          if (state.params.autoRenderAfterSave) {
            await renderStage2({ focusTab: false });
          }
        } catch (error) {
          pushToast({ title: "Metadata failed", message: error.message, variant: "danger" });
        } finally {
          dispatch({ type: "SET_BUSY", key: "fillingMeta", value: false });
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

          const targetParts = targetValue.split(":");
          const isAppTarget = targetValue.startsWith("app.");
          const isServiceMultilangTarget =
            targetParts.length >= 4 &&
            targetParts[0] === "service" &&
            ["env", "port", "volume"].includes(targetParts[2]);
          const isServiceSingleTarget = targetParts.length >= 3 && targetParts[0] === "service" && !isServiceMultilangTarget;

          const appFieldPath = isAppTarget ? targetValue.slice("app.".length) : "";
          const appMultilangFields = new Set(["title", "tagline", "description"]);
          const appSingleFields = new Set([
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
          const isAppMultilangTarget = isAppTarget && (appMultilangFields.has(appFieldPath) || appFieldPath.startsWith("tips."));
          const isAppSingleTarget = isAppTarget && appSingleFields.has(appFieldPath);

          if (isAppMultilangTarget && !isMultilang) {
            pushToast({
              title: "Wrong mode",
              message: "This app target is multi-language. Turn on multi-language mode.",
              variant: "warning",
            });
            return false;
          }
          if (isAppSingleTarget && isMultilang) {
            pushToast({
              title: "Wrong mode",
              message: "This app target is single-language. Turn off multi-language mode.",
              variant: "warning",
            });
            return false;
          }

          if (isServiceMultilangTarget && !isMultilang) {
            pushToast({
              title: "Wrong mode",
              message: "This service target requires multi-language mode (env/port/volume descriptions).",
              variant: "warning",
            });
            return false;
          }
          if (isServiceSingleTarget && isMultilang) {
            pushToast({
              title: "Wrong mode",
              message: "This service target looks like a single-language path. Turn off multi-language mode.",
              variant: "warning",
            });
            return false;
          }

          if (!isAppTarget && !targetValue.startsWith("service:")) {
            pushToast({
              title: "Invalid target",
              message: "Target must start with app. or service:.",
              variant: "warning",
            });
            return false;
          }

          const canMetaUpdateAppFields = new Set([
            "title",
            "tagline",
            "description",
            "category",
            "author",
            "developer",
            "main",
            "port_map",
            "scheme",
            "index",
          ]);
          const shouldUpdateMeta =
            Boolean(state.engine.has_meta) &&
            ((isAppTarget && canMetaUpdateAppFields.has(appFieldPath)) || isServiceMultilangTarget);

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

          if (isMultilang) {
            await requestJSON("/api/stage2/update-multi", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                target: targetValue,
                value: nextValue,
                overwrite_all_languages: true,
                language: languageValue || undefined,
              }),
            });
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
            message: isMultilang ? `Updated ${targetValue} (LLM translated).` : `Updated ${targetValue}.`,
            variant: "success",
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

      const canContinue = useMemo(() => {
        if (state.wizard.stepIndex === 0) {
          return state.engine.has_compose;
        }
        if (state.wizard.stepIndex === 1) {
          return state.engine.has_compose;
        }
        if (state.wizard.stepIndex === 2) {
          return state.engine.has_compose;
        }
        return true;
      }, [state.engine.has_compose, state.engine.has_stage2, state.wizard.stepIndex]);

      const onBack = () => {
        dispatch({ type: "SET_STEP", stepIndex: Math.max(0, state.wizard.stepIndex - 1) });
      };

      const onContinue = () => {
        const current = state.wizard.stepIndex;
        const next = Math.min(STEPS.length - 1, current + 1);
        dispatch({ type: "UNLOCK_STEP", index: next });
        dispatch({ type: "SET_STEP", stepIndex: next });
        if (next === 3 && state.engine.has_compose && !state.renderedYaml.trim()) {
          refreshExportYaml();
        }
      };

      const postLoadHasStage2 = Boolean(state.dialogs?.postLoadHasStage2);
      const showPostLoadChooser = Boolean(state.dialogs?.postLoadChooserOpen);

      const chooseFullWorkflow = () => {
        dispatch({ type: "CLOSE_POST_LOAD_CHOOSER" });
        dispatch({ type: "SET_STEP", stepIndex: 1 });
      };

      const chooseQuickUpdate = () => {
        dispatch({ type: "CLOSE_POST_LOAD_CHOOSER" });
        dispatch({ type: "SET_STEP", stepIndex: 3 });
      };

      const footerRight = useMemo(() => {
        if (state.wizard.stepIndex === 3) {
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
          <Button
            variant="primary"
            disabled={!canContinue}
            onClick={onContinue}
          >
            Continue
          </Button>
        );
      }, [state.wizard.stepIndex, state.engine.has_compose, state.renderedYaml, canContinue]);

      const mainContent = useMemo(() => {
        switch (state.wizard.stepIndex) {
          case 0:
            return (
              <StepLoadCompose
                mode={state.compose.mode}
                onModeChange={(mode) => dispatch({ type: "SET_COMPOSE_MODE", mode })}
                composeText={state.compose.text}
                composeFile={state.compose.file}
                onComposeTextChange={(text) => dispatch({ type: "SET_COMPOSE_TEXT", text })}
                onComposeFileChange={(file) => dispatch({ type: "SET_COMPOSE_FILE", file })}
                onLoadFromFile={loadComposeFromFile}
                onLoadFromText={loadComposeFromText}
                engine={state.engine}
                busy={state.busy.loadingCompose}
              />
            );
          case 1:
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
          case 2:
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
          case 3:
            return (
              <StepExport
                engine={state.engine}
                renderedYaml={state.renderedYaml}
                onRefresh={refreshExportYaml}
                onQuickUpdate={quickUpdateField}
                busy={{ exporting: state.busy.exporting, patchingField: state.busy.patchingField }}
              />
            );
          default:
            return null;
        }
      }, [state]);

      const headerSubtitle = useMemo(() => {
        if (state.engine.has_stage2) {
          return "Rendered output ready for export.";
        }
        if (state.engine.has_compose) {
          return "Compose loaded. Configure metadata, then render.";
        }
        return "Load a docker-compose.yml to begin.";
      }, [state.engine.has_compose, state.engine.has_stage2]);

      return (
        <div className="app">
          <header className="appHeader">
            <div className="appHeader__inner">
              <div className="appHeader__left">
                <div className="appTitleRow">
                  <h1 className="appTitle">CasaOS Compose Visual Editor</h1>
                  <span className="pill pill--muted">Wizard</span>
                </div>
                <p className="appSubtitle">{headerSubtitle}</p>
              </div>
              <div className="appHeader__right">
                <IconButton label="Refresh" loading={state.busy.syncing} onClick={() => syncUIState()}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M20 12a8 8 0 1 1-2.34-5.66"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                    <path
                      d="M20 4v6h-6"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </IconButton>
              </div>
            </div>
          </header>

          <div className="stepperWrap">
            <div className="container">
              <Stepper
                steps={STEPS}
                activeIndex={state.wizard.stepIndex}
                maxEnabledIndex={maxEnabledIndex}
                onStepChange={(index) => dispatch({ type: "SET_STEP", stepIndex: index })}
              />
            </div>
          </div>

          <main className="main">
            <div className="container">{mainContent}</div>
          </main>

          <footer className="footer">
            <div className="container footer__inner">
              <div className="footer__left">
                <Button variant="secondary" disabled={state.wizard.stepIndex === 0} onClick={onBack}>
                  Back
                </Button>
              </div>
              <div className="footer__right">{footerRight}</div>
            </div>
          </footer>

          {showPostLoadChooser && (
            <div
              className="modalBackdrop"
              role="dialog"
              aria-modal="true"
              aria-label="Choose workflow"
            >
              <div className="modalPanel" onClick={(event) => event.stopPropagation()}>
                <Card>
                  <CardHeader
                    title="Choose workflow"
                    subtitle="Pick the best flow for this file. You can always switch later via the stepper."
                  />
                  <CardBody>
                    <div className="stack stack--md">
                      {postLoadHasStage2 ? (
                        <div className="banner banner--success">
                          <div className="banner__title">x-casaos detected</div>
                          <div className="banner__message">This looks like an already-edited CasaOS YAML.</div>
                        </div>
                      ) : (
                        <div className="banner banner--warning">
                          <div className="banner__title">No x-casaos detected</div>
                          <div className="banner__message">This looks like a raw docker-compose.yml.</div>
                        </div>
                      )}

                      <div className="grid2">
                        <div className="banner">
                          <div className="banner__title">Full workflow</div>
                          <div className="banner__message">
                            Use Metadata (Params/LLM), Preview/Render, then Export.
                          </div>
                        </div>
                        <div className="banner">
                          <div className="banner__title">Quick update</div>
                          <div className="banner__message">
                            Patch a single field (multi-language sync) and export immediately.
                          </div>
                        </div>
                      </div>

                      <div className="row row--end row--wrap">
                        <Button
                          variant={postLoadHasStage2 ? "secondary" : "primary"}
                          onClick={chooseFullWorkflow}
                        >
                          Full workflow
                        </Button>
                        <Button
                          variant={postLoadHasStage2 ? "primary" : "secondary"}
                          onClick={chooseQuickUpdate}
                        >
                          Quick update
                        </Button>
                      </div>
                    </div>
                  </CardBody>
                </Card>
              </div>
            </div>
          )}

          <ToastHost toasts={state.toasts} onDismiss={dismissToast} />
        </div>
      );
    }

    const container = document.getElementById("root");
    const reactRoot = ReactDOM.createRoot(container);
    reactRoot.render(<App />);
  }

  bootstrap();
})();
