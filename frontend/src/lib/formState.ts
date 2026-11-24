/**
 * formState.ts — 跨页保留表单输入
 *
 * 为什么需要：
 *   路由一换，页面组件就卸载，useState 里的东西全没了。
 *   用户实际遇到的场景：
 *     在采集页输入了关键词、选好翻页数 → 去样本库看一眼 → 回来
 *     关键词空了、条数变回默认，得重填一遍。
 *   这跟"任务被掐断"是同一类问题：切页把人已经做的工抹掉了。
 *
 * 做法：
 *   模块级 Map 存值，组件重挂载时从这里取初始值。
 *   只在内存里，刷新页面就清空——不假装是"保存"，也不会留下过时数据。
 */

import { useCallback, useEffect, useRef, useState } from "react";

const store = new Map<string, unknown>();

/**
 * 用法和 useState 一样，只是值按 key 跨页面存活。
 *
 * @param key 唯一标识，建议带上页面和字段名，例如 "capture|keyword"
 * @param initial 第一次进入时的默认值
 */
export function useKeptState<T>(
  key: string,
  initial: T,
): [T, (next: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() =>
    store.has(key) ? (store.get(key) as T) : initial,
  );

  /*
   * 用 ref 记住 key：同一组件实例上 key 变了（很少见）也能正确改路由到新槽位，
   * 而不需要卸载重挂载。
   */
  const keyRef = useRef(key);
  keyRef.current = key;

  const set = useCallback((next: T | ((prev: T) => T)) => {
    setValue((prev) => {
      const resolved =
        typeof next === "function" ? (next as (p: T) => T)(prev) : next;
      store.set(keyRef.current, resolved);
      return resolved;
    });
  }, []);

  return [value, set];
}

/** 手动清掉某个槽位（例如"提交成功后清空关键词"） */
export function clearKeptState(key: string): void {
  store.delete(key);
}

/* ---------------- 会扛过刷新的一种 ---------------- */

/**
 * 和 useKeptState 用法一样，但值同时写进 sessionStorage。
 *
 * 为什么还需要另一种：
 *   useKeptState 只在内存里，切页活得下来、刷新就没了。
 *   可是"搜了 20 篇、勾了 3 篇，结果去写稿页转一圈再回来"这种场景，
 *   用户按的可能是刷新、也可能是从别处点回来，对他来说都是"回来"。
 *   搜索结果是他花时间等出来的，不该因为一次刷新白等。
 *
 * 为什么用 sessionStorage 而不是 localStorage：
 *   这是"这一次浏览的现场"，关掉标签页就该清掉；不像项目和历史那样是资产。
 */
export function useSessionState<T>(
  key: string,
  initial: T,
): [T, (next: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    if (store.has(key)) return store.get(key) as T;
    try {
      const raw = sessionStorage.getItem(key);
      if (raw) {
        const parsed = JSON.parse(raw) as T;
        store.set(key, parsed);
        return parsed;
      }
    } catch {
      /* 隐私模式或内容过大：退回默认值，不能让页面白屏 */
    }
    return initial;
  });

  const keyRef = useRef(key);
  keyRef.current = key;

  /* 正文是逐条补进来的，20 篇就是 20 次写盘。攒 400ms 再写一次就够 */
  const timer = useRef<number | null>(null);

  const set = useCallback((next: T | ((prev: T) => T)) => {
    setValue((prev) => {
      const resolved =
        typeof next === "function" ? (next as (p: T) => T)(prev) : next;
      store.set(keyRef.current, resolved);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        try {
          sessionStorage.setItem(keyRef.current, JSON.stringify(store.get(keyRef.current)));
        } catch {
          /* 配额满：内存里那份还在，页内照常可用 */
        }
      }, 400);
      return resolved;
    });
  }, []);

  useEffect(
    () => () => {
      /*
       * 卸载时把攒着的那次写掉，不能只清定时器：
       * 用户勾完最后一篇立刻切页，那次更新还在 400ms 窗口里，
       * 清掉就等于把刚勾的丢了。
       */
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
      }
      if (!store.has(keyRef.current)) return;
      try {
        sessionStorage.setItem(
          keyRef.current,
          JSON.stringify(store.get(keyRef.current)),
        );
      } catch {
        /* 忽略 */
      }
    },
    [],
  );

  return [value, set];
}

/** 清掉某个 session 槽位（两个地方一起清） */
export function clearSessionState(key: string): void {
  store.delete(key);
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* 忽略 */
  }
}
