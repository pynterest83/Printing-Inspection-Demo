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
  speed_m_min: number;
  position_m: number;
  frame_id: number;
  roll: RollSummary;
  lanes: Array<{ lane_id: number; status: "OK" | "NG" }>;
  alarm: Alarm;
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

