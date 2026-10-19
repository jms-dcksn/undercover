import { useCallback, useEffect, useState } from "react";

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = (await response.json()) as { detail?: unknown };
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${String(response.status)}).`,
    );
  }
  return (await response.json()) as T;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The request could not be completed.";
}

export async function post(
  path: string,
  body: Record<string, string>,
): Promise<void> {
  await request<unknown>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

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
