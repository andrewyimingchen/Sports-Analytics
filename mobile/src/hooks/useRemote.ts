import { useCallback, useEffect, useRef, useState } from "react";

import { getJson } from "@/api/client";
import { useApp } from "@/context/AppContext";

interface RemoteState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
  stale: boolean;
  reload: () => Promise<void>;
}

export function useRemote<T>(
  path: string | null,
  query?: Record<string, string | number | boolean | null | undefined>
): RemoteState<T> {
  const { baseUrl, apiKey } = useApp();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [refreshing, setRefreshing] = useState(false);
  const [stale, setStale] = useState(false);
  const mounted = useRef(true);
  const queryKey = JSON.stringify(query ?? {});

  useEffect(() => () => {
    mounted.current = false;
  }, []);

  const load = useCallback(
    async (refresh = false) => {
      if (!path) {
        setLoading(false);
        return;
      }
      if (refresh) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const result = await getJson<T>(baseUrl, path, { apiKey, query });
        if (mounted.current) {
          setData(result.data);
          setStale(result.stale);
        }
      } catch (caught) {
        if (mounted.current) {
          setError(caught instanceof Error ? caught.message : "Something went wrong.");
        }
      } finally {
        if (mounted.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    // queryKey intentionally stabilizes callers that create query objects inline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [apiKey, baseUrl, path, queryKey]
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  return {
    data,
    error,
    loading,
    refreshing,
    stale,
    reload: () => load(true)
  };
}
