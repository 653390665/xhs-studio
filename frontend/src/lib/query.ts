/**
 * query.ts — 轻量 useQuery（不引第三方包）
 *
 * 能力：
 * - useQuery(fn, deps) → { data, loading, error, refetch }
 * - 内存缓存（按 key，默认依赖序列化后的 key）
 * - 失效：invalidate(key) / invalidateAll()
 * - 请求去重：同 key 并发只发一次
 * - 卸载后不 setState（避免警告与内存泄漏）
 * - staleTime：默认 0，命中缓存仍会后台刷新但也立即给旧数据
 *
 * 说明：这里刻意不做 window focus 重取、不做重试风暴。
 * 契约要求"默认 0ms、不锁页面"，所以刷新时保留旧数据，不闪骨架。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "./api";

type QueryKey = string;

interface CacheEntry {
  data: unknown;
  updatedAt: number;
  /** 正在进行中的请求，用于去重 */
  promise?: Promise<unknown>;
}

const cache = new Map<QueryKey, CacheEntry>();

/* ============================================================
   失效通知：让所有订阅者重新取数
   ============================================================ */

type Listener = (key: QueryKey) => void;
const listeners = new Set<Listener>();

export function subscribeInvalidation(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * 让某个 key 的缓存失效。
 * 不传参数 = 全部失效。
 * 前缀匹配：invalidate("notes") 会失效 "notes|page=1" 等。
 */
export function invalidate(key?: string): void {
  if (!key) {
    cache.clear();
    listeners.forEach((fn) => fn(""));
    return;
  }
  for (const existing of Array.from(cache.keys())) {
    if (existing === key || existing.startsWith(`${key}|`)) {
      cache.delete(existing);
    }
  }
  listeners.forEach((fn) => fn(key));
}

export function invalidateAll(): void {
  invalidate();
}

/** 直接写入缓存（乐观更新用） */
export function setQueryData<T>(key: QueryKey, data: T): void {
  cache.set(key, { data, updatedAt: Date.now() });
  listeners.forEach((fn) => fn(key));
}

export function getQueryData<T>(key: QueryKey): T | undefined {
  return cache.get(key)?.data as T | undefined;
}

/* ============================================================
   useQuery
   ============================================================ */

export interface UseQueryOptions {
  /** 为 false 时不自动请求（如未登录） */
  enabled?: boolean;
  /** 缓存多久算新鲜（ms）。默认 0：每次挂载都刷新，但先给旧数据 */
  staleTime?: number;
  /** 自定义缓存 key，不传则由 deps 生成 */
  key?: string;
}

export interface UseQueryResult<T> {
  data: T | undefined;
  loading: boolean;
  /** 首次加载（无任何数据）时为 true；刷新旧数据时为 false */
  initialLoading: boolean;
  error: ApiError | null;
  refetch: () => void;
}

/**
 * deps 变化即重新取数。fn 不需要 useCallback，内部用 ref 保存最新实现。
 * key 由 deps 序列化得到；两个不同请求若想共享缓存，请显式传 key。
 */
export function useQuery<T>(
  fn: () => Promise<T>,
  deps: readonly unknown[] = [],
  options: UseQueryOptions = {},
): UseQueryResult<T> {
  const { enabled = true, staleTime = 0, key: explicitKey } = options;

  // deps 序列化成缓存 key。undefined/null 统一成占位符，保持稳定。
  const derivedKey = useMemo(
    () =>
      explicitKey ??
      deps
        .map((dep) => {
          if (dep === undefined) return "_";
          if (dep === null) return "null";
          if (typeof dep === "object") {
            try {
              return JSON.stringify(dep);
            } catch {
              return String(dep);
            }
          }
          return String(dep);
        })
        .join("|"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [explicitKey, ...deps],
  );

  const fnRef = useRef(fn);
  fnRef.current = fn;

  const cached = cache.get(derivedKey);

  const [data, setData] = useState<T | undefined>(
    () => cached?.data as T | undefined,
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [tick, setTick] = useState(0);

  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const run = useCallback(
    async (force: boolean) => {
      if (!enabled) return;

      const entry = cache.get(derivedKey);
      const isFresh =
        entry !== undefined &&
        entry.data !== undefined &&
        Date.now() - entry.updatedAt < staleTime;

      // 缓存新鲜且非强制刷新：直接用，不发请求
      if (!force && isFresh && entry) {
        setData(entry.data as T);
        setLoading(false);
        return;
      }

      // 已有数据：先展示旧数据，后台刷新（不清空，符合契约"不清空已有结果"）
      //
      // 注意判断的是 entry.data !== undefined，不是 entry。缓存里还有一种
      // 「占位条目」：并发去重时为了挂住在飞的 promise，会先写一条
      // {data: undefined, promise}。把占位当成真实数据，loading 会立刻变
      // false、data 还是 undefined，页面就显示「空」——765 条数据的样本库
      // 会先闪 3 秒「样本库还是空的」，用户以为数据丢了。
      if (entry && entry.data !== undefined) {
        setData(entry.data as T);
        setLoading(false);
      } else {
        setLoading(true);
      }
      setError(null);

      // 并发去重：同 key 已有在飞请求就复用
      let inflight = cache.get(derivedKey)?.promise;
      if (!inflight || force) {
        const promise = fnRef
          .current()
          .then((result) => {
            cache.set(derivedKey, { data: result, updatedAt: Date.now() });
            return result;
          })
          .finally(() => {
            const current = cache.get(derivedKey);
            if (current && current.promise === promise) {
              delete current.promise;
            }
          });

        const seed = cache.get(derivedKey);
        if (seed) {
          seed.promise = promise;
        } else {
          cache.set(derivedKey, {
            data: undefined,
            updatedAt: 0,
            promise,
          });
        }
        inflight = promise;
      }

      const requestId = ++requestIdRef.current;

      try {
        const result = (await inflight) as T;
        // 只接受最后一次请求的结果，避免乱序覆盖
        if (mountedRef.current && requestId === requestIdRef.current) {
          setData(result);
          setError(null);
          setLoading(false);
        }
      } catch (err) {
        if (!mountedRef.current || requestId !== requestIdRef.current) return;
        if (err instanceof DOMException && err.name === "AbortError") return;

        const apiError =
          err instanceof ApiError
            ? err
            : new ApiError(0, "请求失败，请稍后重试", err, "network");
        setError(apiError);
        setLoading(false);
      }
    },
    [derivedKey, enabled, staleTime],
  );

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      if (!cancelled) await run(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [run, enabled, tick]);

  // 失效订阅：同 key 被 invalidate 时重新取数
  useEffect(() => {
    const unsubscribe = subscribeInvalidation((invalidatedKey) => {
      if (
        invalidatedKey === "" ||
        invalidatedKey === derivedKey ||
        derivedKey.startsWith(`${invalidatedKey}|`)
      ) {
        void run(true);
      }
    });
    return unsubscribe;
  }, [derivedKey, run]);

  const refetch = useCallback(() => {
    setTick((value) => value + 1);
  }, []);

  const initialLoading = loading && data === undefined;

  return { data, loading, initialLoading, error, refetch };
}

/* ============================================================
   useMutation — 悲观提交（提交/保存/发布用这个）
   成功后才更新界面，不做假成功。
   ============================================================ */

export interface UseMutationResult<TInput, TOutput> {
  mutate: (input: TInput) => Promise<TOutput>;
  loading: boolean;
  error: ApiError | null;
  reset: () => void;
}

export function useMutation<TInput, TOutput>(
  fn: (input: TInput) => Promise<TOutput>,
  options: { onSuccess?: (result: TOutput, input: TInput) => void } = {},
): UseMutationResult<TInput, TOutput> {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const mountedRef = useRef(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const onSuccessRef = useRef(options.onSuccess);
  onSuccessRef.current = options.onSuccess;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const mutate = useCallback(async (input: TInput): Promise<TOutput> => {
    setLoading(true);
    setError(null);
    try {
      const result = await fnRef.current(input);
      if (mountedRef.current) setLoading(false);
      onSuccessRef.current?.(result, input);
      return result;
    } catch (err) {
      const apiError =
        err instanceof ApiError
          ? err
          : new ApiError(0, "操作失败，请稍后重试", err, "network");
      if (mountedRef.current) {
        setError(apiError);
        setLoading(false);
      }
      throw apiError;
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setLoading(false);
  }, []);

  return { mutate, loading, error, reset };
}
