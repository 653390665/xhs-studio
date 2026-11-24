/**
 * CommandPalette.tsx — 全局搜索 / 命令面板
 *
 * 规范（BRIEF 第 4 节交互细节）：
 * - Cmd/Ctrl+K 打开
 * - 输入 250ms 防抖；输入中保留已有结果 + 顶部细进度条，不清空
 * - 键盘上下选择、Enter 执行、Esc 关闭
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./CommandPalette.css";

export interface Command {
  id: string;
  label: string;
  /** 分组：导航 / 动作 */
  group: string;
  /** 跳转路由或执行动作 */
  run: () => void;
  /** 右侧提示，如快捷键或路径 */
  hint?: string;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  commands: Command[];
  /** 远程搜索：返回额外结果；不传则只过滤本地命令 */
  search?: (query: string) => Promise<Command[]>;
  placeholder?: string;
}

const DEBOUNCE_MS = 250;

export default function CommandPalette({
  open,
  onClose,
  commands,
  search,
  placeholder = "搜索页面、样本、草稿，或输入动作",
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [remoteResults, setRemoteResults] = useState<Command[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  // 打开时重置并聚焦
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCursor(0);
    setRemoteResults([]);
    const t = window.setTimeout(() => inputRef.current?.focus(), 20);
    return () => window.clearTimeout(t);
  }, [open]);

  // 防抖远程搜索：不清空上次结果
  useEffect(() => {
    if (!open || !search) return;
    const q = query.trim();
    if (!q) {
      setRemoteResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const results = await search(q);
        setRemoteResults(results);
      } catch {
        // 搜索失败保留旧结果，不打断输入
      } finally {
        setSearching(false);
      }
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [query, open, search]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const local = q
      ? commands.filter((c) => c.label.toLowerCase().includes(q))
      : commands.filter((c) => c.group === "导航").slice(0, 8);
    return [...local, ...remoteResults];
  }, [commands, query, remoteResults]);

  // 结果变化时归位光标
  useEffect(() => {
    setCursor(0);
  }, [filtered.length]);

  const run = useCallback(
    (cmd: Command) => {
      onClose();
      // 让面板先关，再执行动作（避免焦点竞争）
      window.setTimeout(() => cmd.run(), 0);
    },
    [onClose],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => (filtered.length ? (c + 1) % filtered.length : 0));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) =>
        filtered.length ? (c - 1 + filtered.length) % filtered.length : 0,
      );
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const target = filtered[cursor];
      if (target) run(target);
    }
  };

  // 滚动选中项进入视野
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const el = list.querySelector<HTMLElement>(`[data-idx="${cursor}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  return (
    <div
      className="cp-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="cp" role="dialog" aria-modal="true" aria-label="全局搜索">
        {/* 顶部细进度条：搜索中显示，输入时不清空结果 */}
        <div className="cp__progress" data-on={searching ? "1" : "0"} aria-hidden="true">
          <span />
        </div>

        <input
          ref={inputRef}
          className="cp__input"
          value={query}
          placeholder={placeholder}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          aria-label="搜索输入"
        />

        <div className="cp__list" ref={listRef} role="listbox">
          {filtered.length === 0 ? (
            <div className="cp__empty">
              {searching ? "正在搜索…" : `没有找到「${query}」相关的内容`}
            </div>
          ) : (
            filtered.map((cmd, idx) => (
              <button
                key={`${cmd.group}-${cmd.id}`}
                type="button"
                role="option"
                data-idx={idx}
                aria-selected={idx === cursor}
                className={`cp__item${idx === cursor ? " is-active" : ""}`}
                onMouseEnter={() => setCursor(idx)}
                onClick={() => run(cmd)}
              >
                <span className="cp__group">{cmd.group}</span>
                <span className="cp__label">{cmd.label}</span>
                {cmd.hint ? <span className="cp__hint">{cmd.hint}</span> : null}
              </button>
            ))
          )}
        </div>

        <div className="cp__foot">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> 选择
          </span>
          <span>
            <kbd>Enter</kbd> 打开
          </span>
          <span>
            <kbd>Esc</kbd> 关闭
          </span>
        </div>
      </div>
    </div>
  );
}

/** 全局快捷键：Cmd/Ctrl+K */
export function useCommandPaletteHotkey(onOpen: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpen();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onOpen, enabled]);
}
