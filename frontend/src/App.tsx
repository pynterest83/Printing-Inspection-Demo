import { useEffect, useMemo, useState } from "react";
import { useInspection } from "./useInspection";
import { useInspectionStore } from "./store";
import type { Defect } from "./types";

const number = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function Metric({ label, value, unit, tone = "normal" }: { label: string; value: string; unit?: string; tone?: "normal" | "good" | "bad" }) {
  return (
    <div className={`metric metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {unit && <small>{unit}</small>}
    </div>
  );
}

function DefectCard({ defect, onClick }: { defect: Defect; onClick: () => void }) {
  return (
    <button className="defect-card" onClick={onClick}>
      <div className="defect-thumb-wrap">
        {defect.image_url ? <img src={defect.image_url} alt="" className="defect-thumb" /> : <div className="defect-placeholder" />}
      </div>
      <div className="min-w-0 flex-1 text-left">
        <div className="flex items-center justify-between gap-3">
          <strong className="truncate text-sm text-slate-100">{defect.defect_name}</strong>
          <span className={`severity severity-${defect.severity}`}>{defect.severity}</span>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-slate-400">
          <span>LANE <b>{defect.lane_id}</b></span>
          <span><b>{number.format(defect.position_m)}</b> m</span>
          <span><b>{Math.round(defect.confidence * 100)}</b>%</span>
        </div>
      </div>
    </button>
  );
}

function App() {
  const {
    status,
    defects,
    rolls,
    connected,
    selectedDefect,
    error,
    command,
    refreshDefects,
    setSelectedDefect,
  } = useInspection();
  const [frameToken, setFrameToken] = useState(0);
  const [tab, setTab] = useState<"current" | "history">("current");
  const [rollFilter, setRollFilter] = useState("");

  useEffect(() => {
    const timer = window.setInterval(() => setFrameToken((value) => value + 1), 125);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (tab === "history") void refreshDefects(rollFilter || undefined);
    if (tab === "current" && status) void refreshDefects(status.roll.roll_id);
  }, [tab, rollFilter, refreshDefects, status?.roll.roll_id]);

  const machine = status?.machine_status ?? "IDLE";
  const alarm = status?.alarm;
  const displayedDefects = useMemo(() => {
    const activeRoll = status?.roll.roll_id;
    return defects
      .filter((defect) => tab === "history" ? !rollFilter || defect.roll_id === rollFilter : defect.roll_id === activeRoll)
      .slice(0, 100);
  }, [defects, rollFilter, status?.roll.roll_id, tab]);

  const handleReset = () => {
    if (window.confirm("Archive the current roll and create a new roll?")) void command("reset");
  };

  return (
    <main className="hmi-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark"><span /></div>
          <div>
            <p>PRINTGUARD</p>
            <h1>WEB INSPECTION SYSTEM</h1>
          </div>
        </div>
        <div className="machine-state">
          <i className={`state-dot state-${machine.toLowerCase()}`} />
          <div><span>MACHINE STATUS</span><strong>{machine.replace("_", " ")}</strong></div>
        </div>
        <div className="header-metrics">
          <Metric label="SPEED" value={number.format(status?.speed_m_min ?? 0)} unit="m/min" />
          <Metric label="POSITION" value={number.format(status?.position_m ?? 0)} unit="m" />
          <Metric label="TOTAL" value={number.format(status?.roll.total_m ?? 0)} unit="m" />
          <Metric label="GOOD" value={number.format(status?.roll.good_m ?? 0)} unit="m" tone="good" />
          <Metric label="BAD" value={number.format(status?.roll.bad_m ?? 0)} unit="m" tone="bad" />
          <Metric label="BAD RATIO" value={number.format(status?.roll.bad_ratio ?? 0)} unit="%" tone="bad" />
        </div>
        <div className="controls">
          <button className="control-start" disabled={machine === "RUNNING" || machine === "PLC_STOP"} onClick={() => void command("start")}>START</button>
          <button className="control-stop" disabled={machine !== "RUNNING"} onClick={() => void command("stop")}>STOP</button>
          <button className="control-reset" disabled={machine === "RUNNING"} onClick={handleReset}>RESET</button>
        </div>
      </header>

      {alarm && alarm.level !== "NORMAL" && (
        <section className={`alarm-banner alarm-${alarm.level.toLowerCase()}`}>
          <div className="alarm-icon">!</div>
          <div><span>{alarm.level}</span><strong>{alarm.message}</strong></div>
          <div className="alarm-meta">{alarm.lane_id ? `LANE ${alarm.lane_id} · ` : ""}{number.format(alarm.position_m)} m</div>
        </section>
      )}

      {error && <div className="error-toast" onClick={() => useInspectionStore.getState().setError(null)}>{error}</div>}

      <section className="workspace">
        <div className="live-column">
          <div className="panel live-panel">
            <div className="panel-title">
              <div><i className="live-dot" /><span>LIVE WEB VIEW</span></div>
              <div className="feed-meta"><span>1920 × 600</span><b>{connected ? "LIVE" : "RECONNECTING"}</b></div>
            </div>
            <div className="live-frame-wrap">
              <img className="live-frame" src={`/api/live/frame.jpg?v=${frameToken}`} alt="Live inspection" />
              <div className="scanline" />
              <div className="lane-labels">
                {(status?.lanes ?? Array.from({ length: 5 }, (_, index) => ({ lane_id: index + 1, status: "OK" as const }))).map((lane) => (
                  <span key={lane.lane_id}>LANE {lane.lane_id}</span>
                ))}
              </div>
            </div>
          </div>

          <div className="bottom-grid">
            <div className="panel lane-panel">
              <div className="panel-title"><span>LANE STATUS</span><small>REAL-TIME QUALITY GATE</small></div>
              <div className="lane-grid">
                {(status?.lanes ?? []).map((lane) => (
                  <div key={lane.lane_id} className={`lane-card lane-${lane.status.toLowerCase()}`}>
                    <span>LANE {lane.lane_id}</span><strong>{lane.status}</strong><i />
                  </div>
                ))}
              </div>
            </div>
            <div className="panel roll-panel">
              <div className="panel-title"><span>ACTIVE ROLL</span><small>TRACEABILITY</small></div>
              <div className="roll-data"><span>ROLL ID</span><strong>{status?.roll.roll_id ?? "INITIALIZING"}</strong></div>
              <div className="roll-progress"><i style={{ width: `${Math.min(100, ((status?.position_m ?? 0) / 750) * 100)}%` }} /></div>
              <div className="roll-footer"><span>{number.format(status?.position_m ?? 0)} m</span><span>750.0 m</span></div>
            </div>
          </div>
        </div>

        <aside className="panel defect-panel">
          <div className="panel-title defect-title"><span>DEFECT REGISTER</span><b>{displayedDefects.length.toString().padStart(2, "0")}</b></div>
          <div className="tabs">
            <button className={tab === "current" ? "active" : ""} onClick={() => setTab("current")}>CURRENT ROLL</button>
            <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>HISTORY</button>
          </div>
          {tab === "history" && (
            <select className="roll-select" value={rollFilter} onChange={(event) => setRollFilter(event.target.value)}>
              <option value="">All rolls</option>
              {rolls.map((roll) => <option key={roll.roll_id} value={roll.roll_id}>{roll.roll_id} · {roll.status}</option>)}
            </select>
          )}
          <div className="defect-list">
            {displayedDefects.map((defect) => <DefectCard key={defect.id} defect={defect} onClick={() => setSelectedDefect(defect)} />)}
            {displayedDefects.length === 0 && <div className="empty-state"><i>✓</i><strong>NO DEFECTS RECORDED</strong><span>Inspection events will appear here.</span></div>}
          </div>
          <footer className="system-footer"><i className={connected ? "online" : "offline"} /> API {connected ? "CONNECTED" : "OFFLINE"}<span>ENGINE FRAME {status?.frame_id ?? 0}</span></footer>
        </aside>
      </section>

      {selectedDefect && (
        <div className="modal-backdrop" onClick={() => setSelectedDefect(null)}>
          <div className="defect-modal" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => setSelectedDefect(null)}>×</button>
            <div className="modal-image">{selectedDefect.image_url && <img src={selectedDefect.image_url} alt={selectedDefect.defect_name} />}</div>
            <div className="modal-content">
              <span className={`severity severity-${selectedDefect.severity}`}>{selectedDefect.severity}</span>
              <h2>{selectedDefect.defect_name}</h2>
              <p>{selectedDefect.id}</p>
              <dl>
                <div><dt>Roll</dt><dd>{selectedDefect.roll_id}</dd></div>
                <div><dt>Lane</dt><dd>{selectedDefect.lane_id}</dd></div>
                <div><dt>Position</dt><dd>{number.format(selectedDefect.position_m)} m</dd></div>
                <div><dt>Confidence</dt><dd>{Math.round(selectedDefect.confidence * 100)}%</dd></div>
                <div><dt>Length</dt><dd>{number.format(selectedDefect.length_mm ?? 0)} mm</dd></div>
                <div><dt>Detected</dt><dd>{new Date(selectedDefect.timestamp).toLocaleString()}</dd></div>
              </dl>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
