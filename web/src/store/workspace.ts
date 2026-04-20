import { create } from "zustand";

export type PreviewTab = "compose" | "meta" | "rendered";
export type NoticeTone = "info" | "success" | "error";

interface Notice {
  tone: NoticeTone;
  message: string;
}

interface WorkspaceState {
  composeName: string;
  previewTab: PreviewTab;
  settingsOpen: boolean;
  notice: Notice | null;
  setComposeName: (value: string) => void;
  setPreviewTab: (value: PreviewTab) => void;
  setSettingsOpen: (value: boolean) => void;
  setNotice: (notice: Notice | null) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  composeName: "",
  previewTab: "rendered",
  settingsOpen: false,
  notice: null,
  setComposeName: (value) => set({ composeName: value }),
  setPreviewTab: (value) => set({ previewTab: value }),
  setSettingsOpen: (value) => set({ settingsOpen: value }),
  setNotice: (notice) => set({ notice }),
}));
