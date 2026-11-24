/**
 * useSubPath.ts — 从当前 URL 里取一级子路径
 *
 * 例如 /materials/capture → "capture"
 *      /refine               → ""
 *
 * 用它替代把 sub 当 prop 传：路由是唯一事实来源，
 * 直接刷新深链接时也不会退回到默认标签。
 */

import { useLocation } from "react-router-dom";

export function useSubPath(root: string): string {
  const { pathname } = useLocation();
  const prefix = `/${root}`;

  if (!pathname.startsWith(prefix)) return "";

  const rest = pathname.slice(prefix.length).replace(/^\/+/, "");
  const segment = rest.split("/")[0] ?? "";

  return segment;
}
