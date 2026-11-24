/**
 * Icon.tsx — 内联 SVG 图标（自己写，不引图标包）
 *
 * 风格统一：24×24 viewBox、1.5 描边、圆头圆角、currentColor。
 * 线条偏细，符合编辑部"栏线"的语言，不做填充式图标。
 */

import type { CSSProperties } from "react";

export interface IconProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
  /** 描边宽度，默认 1.5 */
  strokeWidth?: number;
}

type IconComponent = (props: IconProps) => JSX.Element;

function createBase(paths: React.ReactNode): IconComponent {
  return function Icon({
    size = 16,
    className,
    style,
    strokeWidth = 1.5,
  }: IconProps) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        style={style}
        aria-hidden="true"
        focusable="false"
      >
        {paths}
      </svg>
    );
  };
}

/* ---------- 8 个一级导航图标 ---------- */

/** 总览：稿纸 + 折角 */
export const IconOverview = createBase(
  <>
    <path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z" />
    <path d="M13 3v6h6" />
    <path d="M8.5 13h7M8.5 17h4.5" />
  </>,
);

/** 素材：层叠的取景框（采集/样本） */
export const IconMaterials = createBase(
  <>
    <rect x="3" y="5" width="13" height="13" rx="1.5" />
    <path d="M8 18h11a2 2 0 0 0 2-2V8" />
    <path d="M3 13.5l3.2-3.2 3 3 2.3-2.3 4.5 4.5" />
    <circle cx="7" cy="8.5" r="1.1" />
  </>,
);

/** 选题：清单 + 勾选 */
export const IconTopics = createBase(
  <>
    <path d="M9 6h11M9 12h11M9 18h7" />
    <path d="M4 5.5l1.2 1.2L7.5 4.4" />
    <path d="M4 11.5l1.2 1.2L7.5 10.4" />
    <circle cx="5.2" cy="18" r="1.2" />
  </>,
);

/** 提炼：三点汇聚成一条线（证据流） */
export const IconDistill = createBase(
  <>
    <circle cx="5" cy="6" r="1.6" />
    <circle cx="5" cy="18" r="1.6" />
    <circle cx="12" cy="12" r="1.6" />
    <path d="M6.4 6.7L10.6 11M6.4 17.3L10.6 13" />
    <path d="M13.6 12H21" />
  </>,
);

/** 工作台：台面上摆着一块料，提炼完在这儿动手 */
export const IconStudio = createBase(
  <>
    <path d="M3.5 10.5h17" />
    <path d="M6 10.5V19.5M18 10.5V19.5" />
    <path d="M8.6 10.5V5.3a1.2 1.2 0 0 1 1.2-1.2h4.4a1.2 1.2 0 0 1 1.2 1.2v5.2" />
  </>,
);

/** 写稿：笔尖 */
export const IconDraft = createBase(
  <>
    <path d="M4 20l4.2-1 10-10a2.1 2.1 0 0 0-3-3l-10 10z" />
    <path d="M14.2 6.8l3 3" />
    <path d="M4 20l1-4.2" />
  </>,
);

/** 发布：上行箭头出框 */
export const IconPublish = createBase(
  <>
    <path d="M12 16V4" />
    <path d="M8 8l4-4 4 4" />
    <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
  </>,
);

/** 智能助手：对话气泡 + 光点 */
export const IconAgent = createBase(
  <>
    <path d="M20 12.5a7 7 0 0 1-7 7H9l-4 2v-4.2A7 7 0 0 1 10 5.5h3a7 7 0 0 1 7 7z" />
    <path d="M9.5 12h.01M12.5 12h.01M15.5 12h.01" />
  </>,
);

/** 设置：滑杆 */
export const IconSettings = createBase(
  <>
    <path d="M4 7h9M17 7h3" />
    <circle cx="15" cy="7" r="2" />
    <path d="M4 17h5M13 17h7" />
    <circle cx="11" cy="17" r="2" />
  </>,
);

/* ---------- 通用 ---------- */

/** Skill：三层能力叠成一组 */
export const IconSkill = createBase(
  <>
    <path d="M12 3.5l2.1 3.9 4.4.7-3.2 3.1.8 4.3-4.1-2.1-4.1 2.1.8-4.3L5.5 8.1l4.4-.7z" />
    <path d="M4 19.5h16" />
  </>,
);

export const IconSearch = createBase(
  <>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4 4" />
  </>,
);

export const IconClose = createBase(<path d="M6 6l12 12M18 6L6 18" />);

export const IconCheck = createBase(<path d="M4.5 12.5l5 5 10-11" />);

export const IconAlert = createBase(
  <>
    <path d="M12 4.5l8.5 15h-17z" />
    <path d="M12 10v4.5M12 17.4h.01" />
  </>,
);

export const IconChevronDown = createBase(<path d="M6 9.5l6 6 6-6" />);

export const IconChevronRight = createBase(<path d="M9.5 6l6 6-6 6" />);

export const IconArrowUpRight = createBase(
  <>
    <path d="M7 17L17 7" />
    <path d="M8.5 7H17v8.5" />
  </>,
);

export const IconRefresh = createBase(
  <>
    <path d="M20 12a8 8 0 1 1-2.6-5.9" />
    <path d="M20 4v4.5h-4.5" />
  </>,
);

export const IconLogout = createBase(
  <>
    <path d="M14 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h8" />
    <path d="M17 8.5l3.5 3.5L17 15.5" />
    <path d="M20 12h-9" />
  </>,
);

export const IconCommand = createBase(
  <>
    <path d="M9 6.5A2.5 2.5 0 1 0 6.5 9H17.5A2.5 2.5 0 1 0 15 6.5v11A2.5 2.5 0 1 0 17.5 15H6.5A2.5 2.5 0 1 0 9 17.5z" />
  </>,
);

/** 编辑：笔 */
export const IconEdit = createBase(
  <>
    <path d="M12 20h8" />
    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z" />
  </>,
);

/** 删除：垃圾桶 */
export const IconTrash = createBase(
  <>
    <path d="M4 7h16" />
    <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" />
    <path d="M10 11v6M14 11v6" />
  </>,
);

/** 上传 */
export const IconUpload = createBase(
  <>
    <path d="M12 15V4" />
    <path d="M8 8l4-4 4 4" />
    <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </>,
);

/** 下载 */
export const IconDownload = createBase(
  <>
    <path d="M12 4v11" />
    <path d="M8 11l4 4 4-4" />
    <path d="M4 18v1a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1" />
  </>,
);

/** 筛选 */
export const IconFilter = createBase(<path d="M3 5h18l-7 8v6l-4 2v-8z" />);

/** 加号 */
export const IconPlus = createBase(<path d="M12 5v14M5 12h14" />);

/** 外部链接 */
export const IconExternal = createBase(
  <>
    <path d="M13 5h6v6" />
    <path d="M19 5l-8 8" />
    <path d="M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4" />
  </>,
);

/** 载入中的 inline spinner（不是图标，是动效元素） */
export function Spinner({
  size = 14,
  className,
  label = "载入中",
}: {
  size?: number;
  className?: string;
  label?: string;
}) {
  return (
    <span
      className={className ? `spinner ${className}` : "spinner"}
      role="status"
      aria-label={label}
      style={{
        width: size,
        height: size,
        borderWidth: size >= 18 ? 2 : 1.5,
      }}
    />
  );
}
