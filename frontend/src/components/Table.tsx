/**
 * Table.tsx — 轻量表格
 *
 * 为什么自己写而不是装 antd：
 *   这一套前端刻意只有一个表格需求（素材库 765 条、草稿列表、任务记录），
 *   而 antd 的 Table 带进来的是 rc-table + rc-virtual-list + rc-resize-observer
 *   + rc-tree-select 一整棵依赖树，压缩后 180 KB 起。为了一个表格装一个组件库，
 *   等于把「不装 antd」这条决定当场推翻。
 *
 * 边界写死（多一项都不做）：
 *   columns / rows / rowKey、单列排序、行选择、展开行、固定列宽、前端分页。
 *   不做：虚拟滚动（分页 50 条够用）、列设置、树形、拖拽列、列宽拖拽。
 *
 * 为什么分页默认 50 而不是 100：
 *   素材库一屏最多看十几行，50 条已经翻三屏；再多只是让浏览器多渲染 DOM，
 *   而用户还是要点「下一页」。真要全量扫，用导出。
 */

import { Fragment, useMemo, useState } from "react";
import "./Table.css";

export interface Column<T> {
  key: string;
  title: string;
  /** 数字按 px，字符串原样（如 "40%"）。不给就自适应 */
  width?: number | string;
  align?: "left" | "right" | "center";
  /** 这一列能不能点表头排序 */
  sortable?: boolean;
  /**
   * 排序依据。
   *
   * 必须显式给，不能从 render 的返回值反推：单元格里常常是「12.3 万」这种
   * 人读字符串，按字符串排会把 9 万排在 12 万后面。
   */
  sortValue?: (row: T) => string | number;
  render?: (row: T) => React.ReactNode;
}

export interface TableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string | number;
  /** 选中态受控；不给就不显示勾选列 */
  selectedKeys?: Array<string | number>;
  onSelectedChange?: (keys: Array<string | number>) => void;
  /** 展开行内容；给了才显示展开箭头 */
  renderExpanded?: (row: T) => React.ReactNode;
  /** 前端分页，0 = 不分页 */
  pageSize?: number;
  /** 空表时显示什么 */
  empty?: React.ReactNode;
  /** 行点击（和勾选互不干扰） */
  onRowClick?: (row: T) => void;
  /** 紧凑行高，列表密集时用 */
  dense?: boolean;
}

type SortState = { key: string; dir: "asc" | "desc" } | null;

export default function Table<T>({
  columns,
  rows,
  rowKey,
  selectedKeys,
  onSelectedChange,
  renderExpanded,
  pageSize = 50,
  empty,
  onRowClick,
  dense = false,
}: TableProps<T>) {
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string | number>>(new Set());

  const selectable = selectedKeys !== undefined && onSelectedChange !== undefined;

  /* ---------------- 排序 ---------------- */

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sortValue) return rows;
    const get = column.sortValue;
    const factor = sort.dir === "asc" ? 1 : -1;
    // 浅拷贝：rows 是调用方的数据，排序不能就地改
    return [...rows].sort((a, b) => {
      const left = get(a);
      const right = get(b);
      if (typeof left === "number" && typeof right === "number") {
        return (left - right) * factor;
      }
      return String(left).localeCompare(String(right), "zh-CN") * factor;
    });
  }, [rows, columns, sort]);

  /* ---------------- 分页 ---------------- */

  const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1;
  // 数据变少（比如删掉了半页）时页码可能越界，钳回最后一页而不是显示空表
  const currentPage = Math.min(page, totalPages);
  const visible = useMemo(() => {
    if (pageSize <= 0) return sorted;
    const start = (currentPage - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, currentPage, pageSize]);

  /* ---------------- 选择 ---------------- */

  const selectedSet = useMemo(() => new Set(selectedKeys ?? []), [selectedKeys]);
  const visibleKeys = visible.map(rowKey);
  const allVisibleSelected =
    visibleKeys.length > 0 && visibleKeys.every((key) => selectedSet.has(key));

  function togglePage(checked: boolean) {
    if (!onSelectedChange) return;
    const next = new Set(selectedSet);
    for (const key of visibleKeys) {
      if (checked) next.add(key);
      else next.delete(key);
    }
    onSelectedChange([...next]);
  }

  function toggleRow(key: string | number) {
    if (!onSelectedChange) return;
    const next = new Set(selectedSet);
    // 用 Set 而不是数组 includes：765 条时每点一次都是 O(n²)
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onSelectedChange([...next]);
  }

  /* ---------------- 展开 ---------------- */

  function toggleExpand(key: string | number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function onHeaderClick(column: Column<T>) {
    if (!column.sortable) return;
    setSort((prev) => {
      if (prev?.key !== column.key) return { key: column.key, dir: "desc" };
      // 三态：降序 → 升序 → 不排。默认降序是因为这些列多数是「多看几眼的是大的」
      if (prev.dir === "desc") return { key: column.key, dir: "asc" };
      return null;
    });
  }

  if (rows.length === 0 && empty) {
    return <div className="tbl__empty">{empty}</div>;
  }

  return (
    <div className="tbl">
      <div className="tbl__scroll">
        <table
          className={`tbl__table${dense ? " is-dense" : ""}`}
          role="table"
          aria-rowcount={rows.length}
        >
          <thead>
            <tr>
              {selectable ? (
                <th className="tbl__cell tbl__cell--check" scope="col">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={(e) => togglePage(e.target.checked)}
                    aria-label={allVisibleSelected ? "取消选中本页" : "选中本页"}
                  />
                </th>
              ) : null}
              {renderExpanded ? (
                <th className="tbl__cell tbl__cell--expand" scope="col">
                  <span className="tbl__sr">展开</span>
                </th>
              ) : null}
              {columns.map((column) => {
                const active = sort?.key === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={`tbl__cell${column.sortable ? " is-sortable" : ""}${
                      column.align ? ` is-${column.align}` : ""
                    }${active ? " is-sorted" : ""}`}
                    style={column.width ? { width: column.width } : undefined}
                    aria-sort={
                      active ? (sort?.dir === "asc" ? "ascending" : "descending") : "none"
                    }
                  >
                    {column.sortable ? (
                      <button
                        type="button"
                        className="tbl__sort"
                        onClick={() => onHeaderClick(column)}
                      >
                        {column.title}
                        <span className="tbl__sortMark" aria-hidden="true">
                          {active ? (sort?.dir === "asc" ? "↑" : "↓") : "↕"}
                        </span>
                      </button>
                    ) : (
                      column.title
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const key = rowKey(row);
              const isSelected = selectedSet.has(key);
              const isOpen = expanded.has(key);
              return (
                <Fragment key={key}>
                  <tr
                    className={`tbl__row${isSelected ? " is-selected" : ""}${
                      onRowClick ? " is-clickable" : ""
                    }`}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {selectable ? (
                      <td className="tbl__cell tbl__cell--check">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRow(key)}
                          onClick={(e) => e.stopPropagation()}
                          aria-label="选中这一行"
                        />
                      </td>
                    ) : null}
                    {renderExpanded ? (
                      <td className="tbl__cell tbl__cell--expand">
                        <button
                          type="button"
                          className={`tbl__chev${isOpen ? " is-open" : ""}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(key);
                          }}
                          aria-expanded={isOpen}
                          aria-label={isOpen ? "收起详情" : "展开详情"}
                        >
                          ›
                        </button>
                      </td>
                    ) : null}
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={`tbl__cell${column.align ? ` is-${column.align}` : ""}`}
                      >
                        {column.render
                          ? column.render(row)
                          : String((row as Record<string, unknown>)[column.key] ?? "")}
                      </td>
                    ))}
                  </tr>
                  {renderExpanded && isOpen ? (
                    <tr className="tbl__expandRow">
                      <td
                        className="tbl__cell"
                        colSpan={
                          columns.length + (selectable ? 1 : 0) + 1
                        }
                      >
                        {renderExpanded(row)}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {pageSize > 0 && totalPages > 1 ? (
        <div className="tbl__pager">
          <span className="tbl__count">
            共 {rows.length} 条 · 第 {currentPage}/{totalPages} 页
          </span>
          <div className="tbl__pagerBtns">
            <button
              type="button"
              className="tbl__page"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
            >
              上一页
            </button>
            <button
              type="button"
              className="tbl__page"
              disabled={currentPage >= totalPages}
              onClick={() => setPage(currentPage + 1)}
            >
              下一页
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
