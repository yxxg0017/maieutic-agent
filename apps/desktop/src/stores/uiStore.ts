/** 短生命周期 UI 状态：面板、抽屉、选择与草稿。业务状态不放在这里。 */
import { create } from "zustand";

type WorkspaceTab = "frame" | "sources" | "candidates" | "boundaries";

type UiState = {
  sessionId: string | null;
  workspaceOpen: boolean;
  workspaceTab: WorkspaceTab;
  selectedCandidateIds: string[];
  settingsOpen: boolean;
  setSessionId: (id: string | null) => void;
  setWorkspaceOpen: (open: boolean) => void;
  setWorkspaceTab: (tab: WorkspaceTab) => void;
  toggleCandidate: (id: string) => void;
  setSettingsOpen: (open: boolean) => void;
};

export const useUiStore = create<UiState>((set) => ({
  sessionId: null,
  workspaceOpen: true,
  workspaceTab: "frame",
  selectedCandidateIds: [],
  settingsOpen: false,
  setSessionId: (id) => set({ sessionId: id, selectedCandidateIds: [] }),
  setWorkspaceOpen: (open) => set({ workspaceOpen: open }),
  setWorkspaceTab: (tab) => set({ workspaceTab: tab }),
  toggleCandidate: (id) =>
    set((state) => ({
      selectedCandidateIds: state.selectedCandidateIds.includes(id)
        ? state.selectedCandidateIds.filter((existing) => existing !== id)
        : [...state.selectedCandidateIds, id],
    })),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
}));
