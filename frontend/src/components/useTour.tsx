/**
 * useTour.tsx — 页面引导的共享入口
 *
 * 用法：
 *   const { open, button, node } = usePageTour(TOUR_CAPTURE, "capture");
 *   <PageHeader actions={button} />   // 或和别的按钮放在一起
 *   {node}                            // 放在页面根部
 *
 * 为什么不在每页自动弹：
 *   自动弹只在首页做一次。其他页若也自动弹，切个标签就盖一层遮罩，
 *   反而变成干扰。这些页给一个「带我看一遍」的按钮，想看才看。
 */

import { useCallback, useMemo, useState } from "react";
import Tour, { type TourStep } from "./Tour";
import { hasSeenTour } from "../lib/tour";

export function usePageTour(steps: TourStep[], name: string) {
  const [open, setOpen] = useState(false);

  const show = useCallback(() => setOpen(true), []);
  const close = useCallback(() => setOpen(false), []);

  /** 按钮：没看过时用虚线强调，看过就是普通文字 */
  const button = useMemo(
    () => (
      <button type="button" className="tour-launch" onClick={show}>
        {hasSeenTour(name) ? "再看一遍" : "带我看一遍"}
      </button>
    ),
    [name, show],
  );

  const node = (
    <Tour steps={steps} open={open} onClose={close} name={name} />
  );

  return { open, show, close, button, node };
}
