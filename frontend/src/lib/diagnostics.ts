/**
 * diagnostics.ts — 系统诊断
 *
 * 真实端点：GET /api/system/diagnostics?limit=N
 * 真实结构（已实测）：
 * {
 *   window_days: 7,
 *   summary: { api_errors, failed_tasks, account_issues, template_issues },
 *   api_errors: [{ id, endpoint, method, status, status_code, created_at }],
 *   failed_tasks: [], account_issues: [], template_issues: []
 * }
 *
 * 注意：后端没有 /api/xhs/summary 或 /api/xhs/diagnostics，别用。
 */

import { get } from "./api";

export interface ApiErrorRow {
  id: number | string;
  endpoint: string;
  method?: string;
  status?: string;
  status_code?: number;
  created_at?: string;
}

export interface Diagnostics {
  window_days: number;
  since?: string;
  summary: {
    api_errors: number;
    failed_tasks: number;
    account_issues: number;
    template_issues: number;
  };
  api_errors: ApiErrorRow[];
  failed_tasks: unknown[];
  account_issues: unknown[];
  template_issues: unknown[];
}

export function fetchDiagnostics(limit = 20): Promise<Diagnostics> {
  return get<Diagnostics>(`/api/system/diagnostics?limit=${limit}`);
}
