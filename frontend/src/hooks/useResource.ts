/** Small data-fetching and clock hooks. */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";

export function useResource<T>(
  loader: () => Promise<T>,
  deps: unknown[],
): {
  data: T | null;
  error: string;
  loading: boolean;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    loaderRef
      .current()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof ApiError ? caught.detail : "Network error — could not reach the server.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, error, loading, reload };
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} · Sentinel AI`;
  }, [title]);
}
