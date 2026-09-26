export type MachineStatus = "IDLE" | "RUNNING" | "STOPPED" | "PLC_STOP";
export type AlarmLevel = "NORMAL" | "WARNING" | "ALARM";

export interface Alarm {
  level: AlarmLevel;
  code: string;
  message: string;
  lane_id: number | null;
  position_m: number;
  timestamp: string;
}

export interface RollSummary {
  roll_id: string;
  status: string;
  total_m: number;
  good_m: number;
  bad_m: number;
  bad_ratio: number;
  created_at?: string;
  started_at?: string | null;
  ended_at?: string | null;
  stop_reason?: string | null;
}

export interface InspectionStatus {
  machine_status: MachineStatus;
  detector_mode?: string;
  dataset_mode?: string;
  speed_m_min: number;
  position_m: number;
  frame_id: number;
  roll: RollSummary;
  lanes: Array<{ lane_id: number; status: "OK" | "NG" }>;
  alarm: Alarm;
  performance?: {
    target_speed_m_min: number;
    measured_speed_m_min: number;
    target_input_fps: number;
    input_fps: number;
    processed_fps: number;
    processing_avg_ms: number;
    processing_p95_ms: number;
    dropped_frames: number;
    deadline_misses: number;
    queue_depth: number;
    source_lines_per_second: number;
    processing_window_m: number;
    processing_height_px: number;
    display_window_m: number;
    stream_fps: number;
    stream_width: number;
    stream_height: number;
  };
}

export interface Defect {
  id: string;
  annotation_id: string;
  timestamp: string;
  roll_id: string;
  lane_id: number;
  position_m: number;
  end_position_m: number;
  defect_type: string;
  defect_name: string;
  confidence: number;
  severity: string;
  area_mm2: number | null;
  length_mm: number | null;
  bbox: { x: number; y: number; w: number; h: number };
  image_url: string | null;
}

export interface Envelope<T = unknown> {
  type: "telemetry" | "defect.created" | "alarm.changed" | "machine.changed" | "snapshot";
  sequence: number;
  timestamp: string;
  data: T;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
