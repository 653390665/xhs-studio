/**
 * tour.ts — 引导的本地状态
 *
 * 只存「看过没看过」这一个布尔事实，不上传、不同步。
 * localStorage 在隐私模式下可能抛异常，全部兜住：
 * 读不到当「看过」，避免每次刷新都弹；写不进也不影响使用。
 */

const KEY = (name: string) => `xhs.tour.${name}`;

export function hasSeenTour(name: string): boolean {
  try {
    return localStorage.getItem(KEY(name)) === "done";
  } catch {
    return true;
  }
}

export function markTourSeen(name: string): void {
  try {
    localStorage.setItem(KEY(name), "done");
  } catch {
    /* 隐私模式写不进去，静默忽略 */
  }
}

export function resetTour(name: string): void {
  try {
    localStorage.removeItem(KEY(name));
  } catch {
    /* 同上 */
  }
}
