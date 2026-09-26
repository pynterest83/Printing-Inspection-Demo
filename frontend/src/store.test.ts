import { beforeEach, describe, expect, it } from "vitest";
import { useInspectionStore } from "./store";
import type { Defect } from "./types";

const defect: Defect = {
  id: "DEF-1",
  annotation_id: "DARK-001",
  timestamp: "2026-01-01T00:00:00Z",
  roll_id: "ROLL-1",
  lane_id: 2,
  position_m: 40,
  end_position_m: 40.8,
  defect_type: "dark_spot",
  defect_name: "Dark Spot",
  confidence: 0.96,
  severity: "medium",
  area_mm2: 1.4,
  length_mm: 800,
  bbox: { x: 10, y: 500, w: 40, h: 32 },
  image_url: "/api/defects/DEF-1/thumbnail.jpg",
};

describe("inspection store", () => {
  beforeEach(() => useInspectionStore.getState().setDefects([]));

  it("deduplicates websocket defect events by id", () => {
    useInspectionStore.getState().addDefect(defect);
    useInspectionStore.getState().addDefect(defect);
    expect(useInspectionStore.getState().defects).toHaveLength(1);
  });
});
