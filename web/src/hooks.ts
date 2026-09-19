import { useCallback, useEffect, useState } from 'react';
import type { z } from 'zod';
import { request } from './api';

export function useResource<T>(url: string | null, schema: z.ZodType<T>) {
  const [state, setState] = useState<{ url: string | null; data: T | null; error: Error | null; loading: boolean }>({
    url, data: null, error: null, loading: !!url,
  });
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(n => n + 1), []);
  useEffect(() => {
    if (!url) return;
    const controller = new AbortController();
    setState({ url, data: null, error: null, loading: true });
    void request(url, schema, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setState({ url, data, error: null, loading: false });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({ url, data: null, error: error instanceof Error ? error : new Error('Request failed.'), loading: false });
    });
    return () => controller.abort();
  }, [url, schema, revision]);
  return { ...(state.url === url && url ? state : { data: null, error: null, loading: !!url }), reload };
}
