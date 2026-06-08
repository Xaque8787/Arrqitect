import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { InstalledApp } from "./api";

interface QueueContextValue {
  queue: InstalledApp[];
  count: number;
  refresh: () => void;
}

const QueueContext = createContext<QueueContextValue>({
  queue: [],
  count: 0,
  refresh: () => {},
});

export function QueueProvider({ children }: { children: React.ReactNode }) {
  const [queue, setQueue] = useState<InstalledApp[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    api.queue.list().then(setQueue).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    intervalRef.current = setInterval(refresh, 8000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refresh]);

  return (
    <QueueContext.Provider value={{ queue, count: queue.length, refresh }}>
      {children}
    </QueueContext.Provider>
  );
}

export function useQueue() {
  return useContext(QueueContext);
}
