import { create } from "zustand";
import type { Defect, InspectionStatus, RollSummary } from "./types";

interface InspectionStore {
  status: InspectionStatus | null;
  defects: Defect[];
  rolls: RollSummary[];
  connected: boolean;
  selectedDefect: Defect | null;
  error: string | null;
  setStatus: (status: InspectionStatus) => void;
  setDefects: (defects: Defect[]) => void;
  addDefect: (defect: Defect) => void;
  setRolls: (rolls: RollSummary[]) => void;
  setConnected: (connected: boolean) => void;
  setSelectedDefect: (defect: Defect | null) => void;
  setError: (error: string | null) => void;
}

export const useInspectionStore = create<InspectionStore>((set) => ({
  status: null,
  defects: [],
  rolls: [],
  connected: false,
  selectedDefect: null,
  error: null,
  setStatus: (status) => set({ status }),
  setDefects: (defects) => set({ defects }),
  addDefect: (defect) =>
    set((state) => ({
      defects: state.defects.some((item) => item.id === defect.id)
        ? state.defects
        : [defect, ...state.defects].slice(0, 100),
    })),
  setRolls: (rolls) => set({ rolls }),
  setConnected: (connected) => set({ connected }),
  setSelectedDefect: (selectedDefect) => set({ selectedDefect }),
  setError: (error) => set({ error }),
}));

