import { useCallback, useEffect, useState } from "react";
import { errorMessage, request } from "./api";

export function useResource<T>(
  path: string,
  shouldPoll?: (data: T) => boolean,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const polling = data !== null && (shouldPoll?.(data) ?? false);
  const reload = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const value = await request<T>(path, { signal });
        if (!signal?.aborted) {
          setData(value);
          setError(null);
        }
      } catch (failure) {
        if (!signal?.aborted) setError(errorMessage(failure));
      }
    },
    [path],
  );

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => {
      controller.abort();
    };
  }, [reload, polling]);

  useEffect(() => {
    if (!polling) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      void reload(controller.signal);
    }, 1500);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [polling, reload]);

  return { data, error, reload };
}
