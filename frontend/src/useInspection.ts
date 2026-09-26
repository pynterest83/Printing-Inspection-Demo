import { useCallback, useEffect, useRef } from "react";
import { useInspectionStore } from "./store";
import type { Defect, Envelope, InspectionStatus, Page, RollSummary } from "./types";

async function jsonRequest<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function useInspection() {
  const store = useInspectionStore();
  const retryRef = useRef(0);
  const stoppedRef = useRef(false);
  const lastSequenceRef = useRef(0);

  const refreshRolls = useCallback(async () => {
    const page = await jsonRequest<Page<RollSummary>>("/api/rolls?limit=100");
    useInspectionStore.getState().setRolls(page.items);
  }, []);

  const refreshDefects = useCallback(async (rollId?: string) => {
    const query = rollId ? `?roll_id=${encodeURIComponent(rollId)}&limit=100` : "?limit=100";
    const page = await jsonRequest<Page<Defect>>(`/api/defects${query}`);
    useInspectionStore.getState().setDefects(page.items);
  }, []);

  useEffect(() => {
    stoppedRef.current = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | undefined;

    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/inspection`);
      socket.onopen = () => {
        retryRef.current = 0;
        useInspectionStore.getState().setConnected(true);
        useInspectionStore.getState().setError(null);
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as Envelope;
        const current = useInspectionStore.getState();
        if (message.type === "snapshot") {
          const data = message.data as { status: InspectionStatus; defects: Defect[] };
          lastSequenceRef.current = message.sequence;
          current.setStatus(data.status);
          current.setDefects(data.defects);
        } else if (message.type === "telemetry") {
          current.setStatus(message.data as InspectionStatus);
        } else if (message.type === "defect.created") {
          if (message.sequence <= lastSequenceRef.current) return;
          lastSequenceRef.current = message.sequence;
          current.addDefect(message.data as Defect);
        } else {
          if (message.sequence <= lastSequenceRef.current) return;
          lastSequenceRef.current = message.sequence;
        }
      };
      socket.onclose = () => {
        useInspectionStore.getState().setConnected(false);
        if (stoppedRef.current) return;
        const delays = [1000, 2000, 5000, 10000];
        const delay = delays[Math.min(retryRef.current, delays.length - 1)];
        retryRef.current += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };

    void jsonRequest<InspectionStatus>("/api/status")
      .then((status) => useInspectionStore.getState().setStatus(status))
      .catch((error: Error) => useInspectionStore.getState().setError(error.message));
    void refreshRolls().catch((error: Error) => useInspectionStore.getState().setError(error.message));
    connect();

    return () => {
      stoppedRef.current = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [refreshRolls]);

  const command = useCallback(async (name: "start" | "stop" | "reset") => {
    useInspectionStore.getState().setError(null);
    try {
      const status = await jsonRequest<InspectionStatus>(`/api/demo/${name}`, { method: "POST" });
      useInspectionStore.getState().setStatus(status);
      if (name === "reset") {
        useInspectionStore.getState().setDefects([]);
      }
      await refreshRolls();
    } catch (error) {
      useInspectionStore.getState().setError(error instanceof Error ? error.message : "Command failed");
    }
  }, [refreshRolls]);

  return { ...store, command, refreshDefects, refreshRolls };
}
