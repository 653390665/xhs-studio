import {
  DatabaseOutlined,
  DownloadOutlined,
  PictureOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Image,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Typography,
  message,
} from "antd";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  addDraftAsset,
  fetchDrafts,
  fetchGeneratedImageAssets,
  generateCardBackground,
  registerImageAsset,
  updateDraft,
  uploadAssetFile,
} from "../../../lib/api";
import type { GeneratedImageAsset } from "../../../types";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const WIDTH = 1080;
const HEIGHT = 1440;
const PADDING = 84;
const CONTENT_WIDTH = WIDTH - PADDING * 2;
const FONT_FAMILY = '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif';

type CardStyle = {
  id: string;
  name: string;
  background: string;
  text: string;
  title: string;
  accent: string;
  muted: string;
  codeBackground: string;
};

const CARD_STYLES: CardStyle[] = [
  {
    id: "xiaohongshu",
    name: "小红书红",
    background: "#fff8f6",
    text: "#2b1b18",
    title: "#ff2442",
    accent: "#ff2442",
    muted: "#8a6f68",
    codeBackground: "rgba(255, 36, 66, 0.08)",
  },
  {
    id: "midnight",
    name: "午夜紫",
    background: "#14161c",
    text: "#e8eaf2",
    title: "#ffffff",
    accent: "#8b5cf6",
    muted: "#9aa0b4",
    codeBackground: "rgba(139, 92, 246, 0.16)",
  },
  {
    id: "mint",
    name: "薄荷绿",
    background: "#f0fdf8",
    text: "#123c32",
    title: "#047857",
    accent: "#10b981",
    muted: "#5b8a7d",
    codeBackground: "rgba(16, 185, 129, 0.1)",
  },
  {
    id: "ocean",
    name: "海盐蓝",
    background: "#f0f9ff",
    text: "#0c2f45",
    title: "#0369a1",
    accent: "#0ea5e9",
    muted: "#5c7d92",
    codeBackground: "rgba(14, 165, 233, 0.1)",
  },
  {
    id: "sunset",
    name: "落日橙",
    background: "#fff7ed",
    text: "#3b1d0f",
    title: "#c2410c",
    accent: "#f97316",
    muted: "#8a6a55",
    codeBackground: "rgba(249, 115, 22, 0.1)",
  },
  {
    id: "paper",
    name: "纸张米",
    background: "#f8f5ec",
    text: "#2f2a20",
    title: "#1f1a12",
    accent: "#b45309",
    muted: "#7a6f5b",
    codeBackground: "rgba(180, 83, 9, 0.1)",
  },
  {
    id: "graphite",
    name: "石墨黑",
    background: "#111113",
    text: "#e6e6e9",
    title: "#ffffff",
    accent: "#d4d4d8",
    muted: "#8b8b93",
    codeBackground: "rgba(212, 212, 216, 0.12)",
  },
  {
    id: "cream",
    name: "奶油白",
    background: "#fdf6ec",
    text: "#4b3b2a",
    title: "#2e2216",
    accent: "#d9a441",
    muted: "#8c7a63",
    codeBackground: "rgba(217, 164, 65, 0.14)",
  },
  {
    id: "sakura",
    name: "樱花粉",
    background: "#fff1f5",
    text: "#4a2433",
    title: "#b3154f",
    accent: "#ff7aa2",
    muted: "#a2717f",
    codeBackground: "rgba(255, 122, 162, 0.14)",
  },
  {
    id: "forest",
    name: "森野绿",
    background: "#f2f7f2",
    text: "#1e3a2b",
    title: "#14532d",
    accent: "#2f855a",
    muted: "#5f7d6b",
    codeBackground: "rgba(47, 133, 90, 0.12)",
  },
];

/**
 * 版式（layout）与配色（style）解耦：
 * 4 种版式 × 10 套配色 = 40 种组合，覆盖封面/干货/清单/极简场景。
 */
type CardLayout = {
  id: string;
  name: string;
  /** 封面标题对齐方式 */
  coverAlign: "left" | "center";
  /** 是否绘制装饰圆点 */
  ornaments: boolean;
  /** 封面标题字号倍率 */
  titleScale: number;
  /** 正文所有字号/行距倍率 */
  bodyScale: number;
  /** 正文页头部样式 */
  headerStyle: "bar" | "band" | "minimal";
  /** 页脚标签 */
  footerLabel: string;
  /** 右下角超大页码水印 */
  bigPageNumber: boolean;
};

const CARD_LAYOUTS: CardLayout[] = [
  {
    id: "editorial",
    name: "杂志（默认）",
    coverAlign: "left",
    ornaments: true,
    titleScale: 1,
    bodyScale: 1,
    headerStyle: "bar",
    footerLabel: "XHS CONTENT CARD",
    bigPageNumber: false,
  },
  {
    id: "poster",
    name: "大字报",
    coverAlign: "center",
    ornaments: false,
    titleScale: 1.18,
    bodyScale: 1.12,
    headerStyle: "band",
    footerLabel: "XHS POSTER",
    bigPageNumber: false,
  },
  {
    id: "minimal",
    name: "极简",
    coverAlign: "center",
    ornaments: false,
    titleScale: 0.92,
    bodyScale: 1,
    headerStyle: "minimal",
    footerLabel: "",
    bigPageNumber: false,
  },
  {
    id: "index",
    name: "编号手册",
    coverAlign: "left",
    ornaments: false,
    titleScale: 0.96,
    bodyScale: 0.96,
    headerStyle: "bar",
    footerLabel: "XHS HANDBOOK",
    bigPageNumber: true,
  },
];

const SAMPLE_MARKDOWN = `## 为什么你的笔记没人看？

很多新手一上来就写产品介绍，读者根本不知道这篇笔记和自己有什么关系。

## 3 个立刻能用的方法

- **先写结果**：标题第一句就告诉读者「能得到什么」
- **再写证据**：用前后对比、真实体验或数据降低怀疑
- **最后提问**：用一个具体问题把评论区打开

> 不要追求一次写完美，先发 10 篇，再根据数据调整。

## 一个简单的标题公式

数字 + 身份 + 结果 + 情绪词

例如：**3 个方法，普通人也能做出爆款笔记**

收藏这篇，评论区告诉我你最想先试哪一步。#自媒体 #运营 #副业`;

type BlockType = "h1" | "h2" | "h3" | "p" | "bullet" | "quote" | "code";

type Block = {
  type: BlockType;
  text: string;
  /** 列表项开头的加粗短语，例如 "- **先写结果**：..." 中的「先写结果」 */
  lead?: string;
};

type PreparedBlock = {
  type: BlockType;
  lines: string[];
  font: string;
  lineHeight: number;
  color: string;
  before: number;
  after: number;
  indent: number;
  marker: string;
  background: string;
  lead?: string;
};

function cleanInline(text: string): string {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.*?)\1/g, "$2")
    .replace(/(\*|_)(.*?)\1/g, "$2")
    .replace(/`([^`]+)`/g, "$1");
}

function parseMarkdown(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  let paragraph: string[] = [];
  let code: string[] = [];
  let inCode = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ type: "p", text: cleanInline(paragraph.join(" ")) });
    paragraph = [];
  };
  const flushCode = () => {
    if (!code.length) return;
    blocks.push({ type: "code", text: code.join("\n") });
    code = [];
  };

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    if (trimmed.startsWith("```")) {
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        flushParagraph();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(rawLine);
      continue;
    }
    if (!trimmed) {
      flushParagraph();
      continue;
    }
    if (trimmed.startsWith("### ")) {
      flushParagraph();
      blocks.push({ type: "h3", text: cleanInline(trimmed.slice(4)) });
    } else if (trimmed.startsWith("## ")) {
      flushParagraph();
      blocks.push({ type: "h2", text: cleanInline(trimmed.slice(3)) });
    } else if (trimmed.startsWith("# ")) {
      flushParagraph();
      blocks.push({ type: "h1", text: cleanInline(trimmed.slice(2)) });
    } else if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph();
      const bulletText = trimmed.replace(/^[-*]\s+/, "");
      const leadMatch = bulletText.match(/^\s*(?:\*\*|__)(.+?)(?:\*\*|__)\s*[:：]?\s*(.*)$/);
      blocks.push({
        type: "bullet",
        text: cleanInline(leadMatch ? leadMatch[2] : bulletText),
        lead: leadMatch ? cleanInline(leadMatch[1]) : "",
      });
    } else if (trimmed.startsWith("> ")) {
      flushParagraph();
      blocks.push({ type: "quote", text: cleanInline(trimmed.slice(2)) });
    } else if (trimmed === "---" || trimmed === "***") {
      flushParagraph();
      blocks.push({ type: "p", text: "— — —" });
    } else {
      paragraph.push(trimmed);
    }
  }
  flushParagraph();
  flushCode();
  return blocks;
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const paragraph of text.split("\n")) {
    if (!paragraph) {
      lines.push("");
      continue;
    }
    let line = "";
    for (const character of Array.from(paragraph)) {
      const next = line + character;
      if (line && ctx.measureText(next).width > maxWidth) {
        lines.push(line);
        line = character;
      } else {
        line = next;
      }
    }
    if (line) lines.push(line);
  }
  return lines.length ? lines : [""];
}

function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function hexToRgb(color: string): { r: number; g: number; b: number } {
  const hex = (color || "#000000").replace("#", "");
  const full = hex.length === 3 ? hex.split("").map((char) => char + char).join("") : hex;
  const value = Number.parseInt(full, 16);
  if (!Number.isFinite(value)) return { r: 0, g: 0, b: 0 };
  return { r: (value >> 16) & 255, g: (value >> 8) & 255, b: value & 255 };
}

function withAlpha(color: string, alpha: number): string {
  if (color.startsWith("rgba") || color.startsWith("rgb")) return color;
  const { r, g, b } = hexToRgb(color);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function isDarkColor(color: string): boolean {
  const { r, g, b } = hexToRgb(color);
  return 0.299 * r + 0.587 * g + 0.114 * b < 140;
}

/** 背景：底色 + 对角渐变光晕，避免整页死平。 */
function drawCardBackground(ctx: CanvasRenderingContext2D, style: CardStyle) {
  ctx.fillStyle = style.background;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  const dark = isDarkColor(style.background);
  const gradient = ctx.createLinearGradient(0, 0, WIDTH, HEIGHT);
  gradient.addColorStop(0, withAlpha(style.accent, dark ? 0.16 : 0.09));
  gradient.addColorStop(0.48, "rgba(0,0,0,0)");
  gradient.addColorStop(1, withAlpha(style.accent, dark ? 0.08 : 0.12));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  ctx.save();
  ctx.globalAlpha = dark ? 0.22 : 0.14;
  ctx.fillStyle = style.accent;
  ctx.beginPath();
  ctx.arc(WIDTH + 90, 40, 330, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = dark ? 0.08 : 0.05;
  ctx.beginPath();
  ctx.arc(-60, HEIGHT - 60, 280, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawDotGrid(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  cols: number,
  rows: number,
  gap: number,
  color: string,
) {
  ctx.save();
  ctx.fillStyle = color;
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      ctx.beginPath();
      ctx.arc(x + col * gap, y + row * gap, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawSpacedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  spacing: number,
  align: "left" | "center" = "left",
) {
  const chars = Array.from(text);
  const widths = chars.map((char) => ctx.measureText(char).width);
  const total = widths.reduce((sum, width) => sum + width, 0) + spacing * Math.max(0, chars.length - 1);
  let cursor = align === "center" ? x - total / 2 : x;
  chars.forEach((char, index) => {
    ctx.fillText(char, cursor, y);
    cursor += widths[index] + spacing;
  });
  return total;
}

function truncateToWidth(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let result = "";
  for (const char of Array.from(text)) {
    if (ctx.measureText(`${result}${char}…`).width > maxWidth) break;
    result += char;
  }
  return `${result}…`;
}

/** 图片按 cover 方式裁进圆角容器。 */
function drawRoundedImage(
  ctx: CanvasRenderingContext2D,
  image: HTMLImageElement,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  ctx.save();
  roundedRect(ctx, x, y, width, height, radius);
  ctx.clip();
  const ratio = Math.max(width / image.width, height / image.height);
  const drawWidth = image.width * ratio;
  const drawHeight = image.height * ratio;
  ctx.drawImage(image, x + (width - drawWidth) / 2, y + (height - drawHeight) / 2, drawWidth, drawHeight);
  ctx.restore();
}

function drawCover(
  ctx: CanvasRenderingContext2D,
  style: CardStyle,
  layout: CardLayout,
  documentTitle: string,
  subtitle: string,
  markdown: string,
  backgroundImage?: HTMLImageElement | null,
) {
  const centered = layout.coverAlign === "center";
  const anchorX = centered ? WIDTH / 2 : PADDING;
  const dark = isDarkColor(style.background);

  drawCardBackground(ctx, style);

  if (layout.ornaments) {
    drawDotGrid(ctx, WIDTH - 300, 210, 5, 4, 30, withAlpha(style.accent, dark ? 0.4 : 0.3));
    ctx.save();
    ctx.strokeStyle = withAlpha(style.accent, dark ? 0.4 : 0.28);
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(PADDING + 40, 300, 120, -Math.PI * 0.4, Math.PI * 0.55);
    ctx.stroke();
    ctx.restore();
  }

  if (centered) ctx.textAlign = "center";

  const eyebrow = (layout.footerLabel || "XHS CONTENT CARD").replace(/_/g, " ");
  ctx.fillStyle = style.accent;
  ctx.font = `bold 22px ${FONT_FAMILY}`;
  if (centered) {
    drawSpacedText(ctx, eyebrow, WIDTH / 2, 150, 5, "center");
  } else {
    drawSpacedText(ctx, eyebrow, PADDING, 150, 5);
  }

  ctx.fillStyle = style.muted;
  ctx.font = `22px ${FONT_FAMILY}`;
  ctx.fillText(new Date().toLocaleDateString("zh-CN"), anchorX, 192);

  const titleLength = Array.from(documentTitle || "").length;
  const baseTitleSize = titleLength <= 12 ? 104 : titleLength <= 18 ? 90 : titleLength <= 26 ? 78 : 66;
  const titleFontSize = Math.round(baseTitleSize * layout.titleScale);
  ctx.font = `bold ${titleFontSize}px ${FONT_FAMILY}`;
  const titleLines = wrapText(ctx, documentTitle || "未命名内容", CONTENT_WIDTH).slice(0, 4);
  let y = 300;
  ctx.fillStyle = style.title;
  for (const line of titleLines) {
    if (backgroundImage) {
      ctx.save();
      ctx.shadowColor = "rgba(0,0,0,0.25)";
      ctx.shadowBlur = 22;
      ctx.fillText(line, anchorX, y);
      ctx.restore();
    } else {
      ctx.fillText(line, anchorX, y);
    }
    y += Math.round(titleFontSize * 1.18);
  }

  y += 14;
  const underlineW = centered ? 96 : 132;
  ctx.fillStyle = style.accent;
  roundedRect(ctx, centered ? WIDTH / 2 - underlineW / 2 : PADDING, y, underlineW, 10, 5);
  ctx.fill();
  y += 56;

  if (subtitle) {
    ctx.fillStyle = style.muted;
    ctx.font = `29px ${FONT_FAMILY}`;
    const previewLines = wrapText(ctx, subtitle, CONTENT_WIDTH).slice(0, 2);
    for (const line of previewLines) {
      ctx.fillText(line, anchorX, y);
      y += 44;
    }
  }

  // 视觉区：有 AI 图就做成画册式插图，没有图就用图形 + 章节看点
  const artX = PADDING;
  const artY = Math.max(640, y + 36);
  const artW = WIDTH - PADDING * 2;
  const artH = HEIGHT - 240 - artY;

  if (artH > 220) {
    if (backgroundImage) {
      drawRoundedImage(ctx, backgroundImage, artX, artY, artW, artH, 28);
      ctx.save();
      ctx.strokeStyle = withAlpha(style.title, dark ? 0.25 : 0.12);
      ctx.lineWidth = 2;
      roundedRect(ctx, artX, artY, artW, artH, 28);
      ctx.stroke();
      ctx.restore();

      ctx.fillStyle = withAlpha(style.background, 0.9);
      roundedRect(ctx, artX + 24, artY + artH - 62, 124, 38, 19);
      ctx.fill();
      ctx.fillStyle = style.muted;
      ctx.font = `20px ${FONT_FAMILY}`;
      ctx.fillText("AI 视觉", artX + 50, artY + artH - 36);
    } else {
      ctx.save();
      const panel = ctx.createLinearGradient(artX, artY, artX + artW, artY + artH);
      panel.addColorStop(0, withAlpha(style.accent, dark ? 0.24 : 0.14));
      panel.addColorStop(1, withAlpha(style.accent, dark ? 0.06 : 0.03));
      ctx.fillStyle = panel;
      roundedRect(ctx, artX, artY, artW, artH, 28);
      ctx.fill();
      ctx.strokeStyle = withAlpha(style.accent, dark ? 0.35 : 0.22);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(artX + artW - 120, artY + 120, 150, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = withAlpha(style.accent, dark ? 0.18 : 0.1);
      ctx.beginPath();
      ctx.arc(artX + 90, artY + artH - 60, 90, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      const firstHeading = markdown
        .split("\n")
        .map((line) => line.trim())
        .find((line) => line.startsWith("## ") || line.startsWith("# "));
      const highlight = firstHeading ? cleanInline(firstHeading.replace(/^#+\s*/, "")) : "本期看点";
      const blockCount = parseMarkdown(markdown).length;

      ctx.fillStyle = style.accent;
      ctx.font = `bold 20px ${FONT_FAMILY}`;
      drawSpacedText(ctx, "本期看点", artX + 48, artY + 76, 4);

      ctx.fillStyle = style.title;
      ctx.font = `bold 46px ${FONT_FAMILY}`;
      const highlightLines = wrapText(ctx, highlight, artW - 96).slice(0, 3);
      let highlightY = artY + 156;
      for (const line of highlightLines) {
        ctx.fillText(line, artX + 48, highlightY);
        highlightY += 62;
      }

      ctx.fillStyle = style.muted;
      ctx.font = `23px ${FONT_FAMILY}`;
      ctx.textAlign = "right";
      ctx.fillText(`${blockCount} 个内容块 · 滑动查看`, artX + artW - 48, artY + artH - 56);
      ctx.textAlign = "left";
    }
  }

  const hashtags = Array.from(new Set(markdown.match(/#[^\s#]+/g) ?? [])).slice(0, 4);
  const tagY = HEIGHT - 162;
  ctx.font = `23px ${FONT_FAMILY}`;
  ctx.textAlign = "left";
  const tagLabels = hashtags.map((rawTag) => `#${rawTag.replace(/^#/, "")}`);
  const tagWidths = tagLabels.map((label) => ctx.measureText(label).width + 34);
  let tagX = centered
    ? Math.max(PADDING, WIDTH / 2 - tagWidths.reduce((sum, width) => sum + width + 10, -10) / 2)
    : PADDING;
  hashtags.forEach((rawTag, index) => {
    const label = `#${rawTag.replace(/^#/, "")}`;
    const width = tagWidths[index];
    if (tagX + width > WIDTH - PADDING) return;
    ctx.fillStyle = withAlpha(style.accent, dark ? 0.24 : 0.12);
    roundedRect(ctx, tagX, tagY, width, 46, 23);
    ctx.fill();
    ctx.fillStyle = style.accent;
    ctx.fillText(label, tagX + 17, tagY + 32);
    tagX += width + 10;
  });

  ctx.fillStyle = style.muted;
  ctx.font = `21px ${FONT_FAMILY}`;
  ctx.fillText("长按保存 · 内容卡片", anchorX, HEIGHT - 78);

  ctx.textAlign = "left";
}

function scaleFont(font: string, scale: number): string {
  if (scale === 1) return font;
  return font.replace(/(\d+)px/, (_match, size: string) => `${Math.round(Number(size) * scale)}px`);
}

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("背景图加载失败，请重新生成"));
    image.src = src;
  });
}

function prepareBlocks(
  ctx: CanvasRenderingContext2D,
  blocks: Block[],
  style: CardStyle,
  layout: CardLayout,
): PreparedBlock[] {
  const scale = layout.bodyScale;
  const textX = 96;
  const textWidth = WIDTH - textX * 2;

  /** Scale the font first, then wrap — otherwise enlarged text overflows. */
  const prep = (
    type: BlockType,
    text: string,
    font: string,
    lineHeight: number,
    color: string,
    before: number,
    after: number,
    indent: number,
    marker: string,
    background: string,
    maxWidth = textWidth,
    lead = "",
  ): PreparedBlock => {
    const scaledFont = scaleFont(font, scale);
    ctx.font = scaledFont;
    return {
      type,
      lines: wrapText(ctx, text, maxWidth),
      font: scaledFont,
      lineHeight: Math.round(lineHeight * scale),
      color,
      before: Math.round(before * scale),
      after: Math.round(after * scale),
      indent,
      marker,
      background,
      lead,
    };
  };

  return blocks.map((block) => {
    if (block.type === "h1") {
      return prep("h1", block.text, `bold 50px ${FONT_FAMILY}`, 66, style.title, 26, 20, 0, "", "");
    }
    if (block.type === "h2") {
      return prep("h2", block.text, `bold 42px ${FONT_FAMILY}`, 58, style.title, 40, 18, 0, "", "", textWidth - 80);
    }
    if (block.type === "h3") {
      return prep("h3", block.text, `bold 34px ${FONT_FAMILY}`, 48, style.title, 28, 12, 0, "", "", textWidth - 40);
    }
    if (block.type === "bullet") {
      return prep(
        "bullet",
        block.text,
        `29px ${FONT_FAMILY}`,
        48,
        style.text,
        0,
        10,
        64,
        "",
        "",
        textWidth - 88,
        block.lead || "",
      );
    }
    if (block.type === "quote") {
      return prep(
        "quote",
        block.text,
        `29px ${FONT_FAMILY}`,
        48,
        style.text,
        10,
        16,
        72,
        "",
        "",
        textWidth - 100,
      );
    }
    if (block.type === "code") {
      return prep(
        "code",
        block.text,
        `24px "Cascadia Code", "Consolas", monospace`,
        38,
        style.text,
        12,
        18,
        28,
        "",
        style.codeBackground,
        textWidth - 56,
      );
    }
    return prep("p", block.text, `30px ${FONT_FAMILY}`, 51, style.text, 2, 18, 0, "", "");
  });
}

function renderCards(
  documentTitle: string,
  subtitle: string,
  markdown: string,
  style: CardStyle,
  layout: CardLayout,
  backgroundImage?: HTMLImageElement | null,
): string[] {
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("当前浏览器不支持 Canvas");

  const images: string[] = [];
  drawCover(ctx, style, layout, documentTitle, subtitle, markdown, backgroundImage);
  images.push(canvas.toDataURL("image/png"));

  const blocks = prepareBlocks(ctx, parseMarkdown(markdown), style, layout);
  if (!blocks.length) return images;

  const textX = 96;
  const textWidth = WIDTH - textX * 2;
  const contentTop = 224;
  const contentBottom = HEIGHT - 150;
  const dark = isDarkColor(style.background);

  let pageNo = 0;
  let y = 0;
  let hasContent = false;
  let sectionNo = 0;
  let stepNo = 0;

  const drawPageChrome = () => {
    drawCardBackground(ctx, style);

    ctx.fillStyle = style.accent;
    ctx.fillRect(textX, 96, 44, 6);

    ctx.fillStyle = style.muted;
    ctx.font = `24px ${FONT_FAMILY}`;
    ctx.fillText(truncateToWidth(ctx, documentTitle || "内容卡片", textWidth - 140), textX + 58, 110);

    ctx.textAlign = "right";
    ctx.fillStyle = style.accent;
    ctx.font = `bold 28px ${FONT_FAMILY}`;
    ctx.fillText(String(pageNo).padStart(2, "0"), WIDTH - textX, 112);
    ctx.textAlign = "left";

    ctx.strokeStyle = withAlpha(style.text, 0.12);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(textX, 142);
    ctx.lineTo(WIDTH - textX, 142);
    ctx.stroke();

    ctx.strokeStyle = withAlpha(style.text, 0.1);
    ctx.beginPath();
    ctx.moveTo(textX, HEIGHT - 104);
    ctx.lineTo(WIDTH - textX, HEIGHT - 104);
    ctx.stroke();

    ctx.fillStyle = style.muted;
    ctx.font = `20px ${FONT_FAMILY}`;
    ctx.fillText((layout.footerLabel || "XHS CONTENT CARD").replace(/_/g, " "), textX, HEIGHT - 64);
    ctx.textAlign = "right";
    ctx.fillText(`PAGE ${String(pageNo).padStart(2, "0")}`, WIDTH - textX, HEIGHT - 64);
    ctx.textAlign = "left";

    if (layout.bigPageNumber) {
      ctx.save();
      ctx.globalAlpha = 0.06;
      ctx.fillStyle = style.accent;
      ctx.font = `bold 240px ${FONT_FAMILY}`;
      ctx.textAlign = "right";
      ctx.fillText(String(pageNo), WIDTH - PADDING / 2, HEIGHT - PADDING - 40);
      ctx.restore();
      ctx.textAlign = "left";
    }
  };

  const newPage = () => {
    pageNo += 1;
    drawPageChrome();
    y = contentTop;
    hasContent = false;
  };

  const finishPage = () => {
    if (!hasContent) return;
    images.push(canvas.toDataURL("image/png"));
  };

  const drawHeading = (block: PreparedBlock) => {
    if (block.type === "h1") {
      ctx.fillStyle = style.title;
      ctx.font = block.font;
      block.lines.forEach((line, index) => {
        ctx.fillText(line, textX, y + block.lineHeight * 0.78 + index * block.lineHeight);
      });
      const underlineY = y + block.lines.length * block.lineHeight + 6;
      ctx.fillStyle = style.accent;
      roundedRect(ctx, textX, underlineY, 88, 8, 4);
      ctx.fill();
      return;
    }
    if (block.type === "h2") {
      const chip = 54;
      ctx.fillStyle = style.accent;
      roundedRect(ctx, textX, y + 2, chip, chip, 16);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.font = `bold 26px ${FONT_FAMILY}`;
      ctx.textAlign = "center";
      ctx.fillText(String(sectionNo).padStart(2, "0"), textX + chip / 2, y + 38);
      ctx.textAlign = "left";

      ctx.fillStyle = style.title;
      ctx.font = block.font;
      block.lines.forEach((line, index) => {
        ctx.fillText(line, textX + 76, y + 42 + index * block.lineHeight);
      });
      return;
    }
    ctx.fillStyle = style.accent;
    roundedRect(ctx, textX, y + 8, 6, 30, 3);
    ctx.fill();
    ctx.fillStyle = style.title;
    ctx.font = block.font;
    block.lines.forEach((line, index) => {
      ctx.fillText(line, textX + 24, y + 34 + index * block.lineHeight);
    });
  };

  newPage();

  for (const block of blocks) {
    if (block.type === "h1" || block.type === "h2" || block.type === "h3") {
      const need = block.lines.length * block.lineHeight + 30;
      const ahead = block.type === "h2" ? 160 : 120;
      if (hasContent && contentBottom - y - block.before < need + ahead) {
        finishPage();
        newPage();
      }
      y += block.before;
      if (block.type === "h2") sectionNo += 1;
      hasContent = true;
      drawHeading(block);
      y += block.lines.length * block.lineHeight + block.after;
      continue;
    }

    const isCard = block.type === "bullet" || block.type === "quote" || block.type === "code";
    const padTop = isCard ? (block.type === "bullet" ? 22 : 26) : 0;
    const padBottom = isCard ? 20 : 0;
    const leadH = block.type === "bullet" && block.lead ? 42 : 0;

    y += block.before;
    let remaining = [...block.lines];
    let firstChunk = true;

    while (remaining.length) {
      const available = contentBottom - y - padTop - padBottom - (firstChunk ? leadH : 0);
      let maxLines = Math.floor(available / block.lineHeight);

      if (maxLines < 1) {
        if (hasContent) {
          finishPage();
          newPage();
          continue;
        }
        maxLines = 1;
      }

      const chunk = remaining.slice(0, maxLines);
      remaining = remaining.slice(maxLines);
      hasContent = true;

      if (block.type === "bullet") {
        stepNo += 1;
        const cardX = textX - 18;
        const cardW = textWidth + 36;
        const cardH = padTop + (firstChunk ? leadH : 0) + chunk.length * block.lineHeight + padBottom;

        ctx.fillStyle = dark ? withAlpha("#ffffff", 0.06) : withAlpha("#ffffff", 0.68);
        roundedRect(ctx, cardX, y, cardW, cardH, 20);
        ctx.fill();
        ctx.strokeStyle = withAlpha(style.text, dark ? 0.12 : 0.07);
        ctx.lineWidth = 2;
        roundedRect(ctx, cardX, y, cardW, cardH, 20);
        ctx.stroke();

        if (firstChunk) {
          ctx.fillStyle = style.accent;
          ctx.beginPath();
          ctx.arc(cardX + 44, y + padTop + 19, 20, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = "#ffffff";
          ctx.font = `bold 22px ${FONT_FAMILY}`;
          ctx.textAlign = "center";
          ctx.fillText(String(stepNo), cardX + 44, y + padTop + 27);
          ctx.textAlign = "left";
        }

        if (firstChunk && block.lead) {
          ctx.fillStyle = style.accent;
          ctx.font = `bold 30px ${FONT_FAMILY}`;
          ctx.fillText(truncateToWidth(ctx, block.lead, textWidth - 90), textX + 64, y + padTop + 32);
        }

        ctx.fillStyle = block.color;
        ctx.font = block.font;
        let lineY = y + padTop + leadH + block.lineHeight * 0.76;
        chunk.forEach((line) => {
          ctx.fillText(line, textX + 64, lineY);
          lineY += block.lineHeight;
        });

        y += cardH + block.after;
      } else if (block.type === "quote") {
        const cardX = textX - 18;
        const cardW = textWidth + 36;
        const cardH = padTop + chunk.length * block.lineHeight + padBottom;

        ctx.fillStyle = withAlpha(style.accent, dark ? 0.2 : 0.09);
        roundedRect(ctx, cardX, y, cardW, cardH, 20);
        ctx.fill();
        ctx.fillStyle = withAlpha(style.accent, 0.5);
        ctx.font = `bold 72px ${FONT_FAMILY}`;
        ctx.fillText("“", textX + 8, y + padTop + 44);

        ctx.fillStyle = block.color;
        ctx.font = block.font;
        let lineY = y + padTop + block.lineHeight * 0.74;
        chunk.forEach((line) => {
          ctx.fillText(line, textX + 72, lineY);
          lineY += block.lineHeight;
        });

        y += cardH + block.after;
      } else if (block.type === "code") {
        const cardX = textX - 18;
        const cardW = textWidth + 36;
        const cardH = padTop + chunk.length * block.lineHeight + padBottom;

        ctx.fillStyle = style.codeBackground;
        roundedRect(ctx, cardX, y, cardW, cardH, 16);
        ctx.fill();

        ctx.fillStyle = block.color;
        ctx.font = block.font;
        let lineY = y + padTop + block.lineHeight * 0.78;
        chunk.forEach((line) => {
          ctx.fillText(line, textX + 24, lineY);
          lineY += block.lineHeight;
        });

        y += cardH + block.after;
      } else {
        ctx.fillStyle = block.color;
        ctx.font = block.font;
        let lineY = y + block.lineHeight * 0.78;
        chunk.forEach((line) => {
          ctx.fillText(line, textX + block.indent, lineY);
          lineY += block.lineHeight;
        });
        y += chunk.length * block.lineHeight + block.after;
      }

      if (remaining.length) {
        finishPage();
        newPage();
      }
      firstChunk = false;
    }
  }

  finishPage();
  return images;
}

export function XhsCardStudioPage({ embedded = false }: { embedded?: boolean } = {}) {
  const location = useLocation();
  const navigate = useNavigate();
  const incoming = location.state as { title?: string; body?: string; draftId?: number } | null;
  const [linkedDraftId, setLinkedDraftId] = useState<number | null>(incoming?.draftId ?? null);
  const draftId = linkedDraftId;
  const [draftOptions, setDraftOptions] = useState<Array<{ value: number; label: string }>>([]);
  const [documentTitle, setDocumentTitle] = useState(incoming?.title || "3 个方法，普通人也能做出爆款笔记");
  const [subtitle, setSubtitle] = useState(
    incoming?.title ? "来自草稿工坊的正文，已自动带入" : "把长文变成适合小红书发布的多页卡片",
  );
  const [markdown, setMarkdown] = useState(incoming?.body || SAMPLE_MARKDOWN);
  const [uploading, setUploading] = useState(false);
  const [attachedCount, setAttachedCount] = useState(0);
  const [savingLibrary, setSavingLibrary] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [libraryAssets, setLibraryAssets] = useState<GeneratedImageAsset[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [styleId, setStyleId] = useState("xiaohongshu");
  const [layoutId, setLayoutId] = useState("editorial");
  const [pages, setPages] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [aiBgUrl, setAiBgUrl] = useState<string | null>(null);
  const [bgPrompt, setBgPrompt] = useState("极简编辑风插画，早餐桌与咖啡，柔和自然光，留白，无文字，适合小红书封面");
  const [bgGenerating, setBgGenerating] = useState(false);
  const [useAiBg, setUseAiBg] = useState(true);

  useEffect(() => {
    if (!incoming) return;
    if (incoming.title) setDocumentTitle(incoming.title);
    if (incoming.body) {
      setMarkdown(incoming.body);
      setSubtitle("来自草稿工坊的正文，已自动带入");
    }
    setPages([]);
  }, [incoming]);

  useEffect(() => {
    if (draftId) return;
    void fetchDrafts("xhs", { page: 1, page_size: 50 })
      .then((result) =>
        setDraftOptions(
          result.items.map((draft) => ({
            value: draft.id,
            label: draft.title || `草稿 #${draft.id}`,
          })),
        ),
      )
      .catch(() => setDraftOptions([]));
  }, [draftId]);

  async function renderPreview(
    nextStyleId = styleId,
    nextLayoutId = layoutId,
    bgOverride: string | null = aiBgUrl,
  ) {
    if (!markdown.trim()) {
      message.warning("请输入 Markdown 内容");
      return;
    }
    setGenerating(true);
    try {
      await document.fonts?.ready;
      const nextStyle = CARD_STYLES.find((item) => item.id === nextStyleId) ?? CARD_STYLES[0];
      const nextLayout = CARD_LAYOUTS.find((item) => item.id === nextLayoutId) ?? CARD_LAYOUTS[0];
      const background = useAiBg && bgOverride ? await loadImageElement(bgOverride) : null;
      const images = renderCards(
        documentTitle.trim() || "未命名内容",
        subtitle.trim(),
        markdown,
        nextStyle,
        nextLayout,
        background,
      );
      setPages(images);
      message.success(`已生成 ${images.length} 张卡片`);
    } catch (renderError) {
      message.error(renderError instanceof Error ? renderError.message : "卡片渲染失败");
    } finally {
      setGenerating(false);
    }
  }

  function handleStyleChange(value: string) {
    setStyleId(value);
    if (pages.length) {
      void renderPreview(value, layoutId);
    }
  }

  function handleLayoutChange(value: string) {
    setLayoutId(value);
    if (pages.length) {
      void renderPreview(styleId, value);
    }
  }

  async function handleGenerateBackground() {
    if (!bgPrompt.trim()) {
      message.warning("请填写背景描述");
      return;
    }
    setBgGenerating(true);
    try {
      const result = await generateCardBackground({ prompt: bgPrompt.trim() });
      setAiBgUrl(result.url);
      setUseAiBg(true);
      message.success(`背景图已生成（${(result as { model?: string }).model ?? ""}）`);
      if (pages.length) {
        void renderPreview(styleId, layoutId, result.url);
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "背景生成失败，请检查图片模型配置");
    } finally {
      setBgGenerating(false);
    }
  }

  function downloadAll() {
    if (!pages.length) return;
    pages.forEach((url, index) => {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `xhs-card-${String(index + 1).padStart(2, "0")}.png`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    });
    message.success("已开始下载，请在浏览器下载列表中查看");
  }

  async function attachCardsToDraft() {
    if (!draftId) {
      message.warning("请从草稿工坊点「转为图文卡片」进入，才能关联目标草稿");
      return;
    }
    if (!pages.length) {
      message.warning("请先生成预览");
      return;
    }
    setUploading(true);
    try {
      let count = 0;
      for (let index = 0; index < pages.length; index += 1) {
        const blob = await (await fetch(pages[index])).blob();
        const file = new File(
          [blob],
          `xhs-card-${String(index + 1).padStart(2, "0")}.png`,
          { type: "image/png" },
        );
        const uploaded = await uploadAssetFile(file);
        await addDraftAsset(draftId, {
          asset_type: "image",
          url: uploaded.download_url,
          local_path: uploaded.file_name,
        });
        count += 1;
      }
      setAttachedCount((current) => current + count);
      // 卡片只回填草稿，不在这里创建发布任务；发布必须从草稿工坊送入发布中心。
      await updateDraft(draftId, { title: documentTitle, body: markdown });
      message.success(`已把 ${count} 张卡片加入草稿 #${draftId}；确认后去发布中心送发布。`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "加入草稿失败");
    } finally {
      setUploading(false);
    }
  }

  async function saveCardsToLibrary() {
    if (!pages.length) {
      message.warning("请先生成预览");
      return;
    }
    setSavingLibrary(true);
    try {
      let count = 0;
      for (let index = 0; index < pages.length; index += 1) {
        const blob = await (await fetch(pages[index])).blob();
        const file = new File(
          [blob],
          `xhs-card-${Date.now()}-${index + 1}.png`,
          { type: "image/png" },
        );
        const uploaded = await uploadAssetFile(file);
        await registerImageAsset({
          file_name: uploaded.file_name,
          prompt: documentTitle || "卡片导出",
          kind: "card",
          params: {
            page: index + 1,
            total: pages.length,
            style: styleId,
            layout: layoutId,
          },
        });
        count += 1;
      }
      message.success(`已保存 ${count} 张卡片到图片素材`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "保存到图片素材失败");
    } finally {
      setSavingLibrary(false);
    }
  }

  async function openAssetPicker() {
    setPickerOpen(true);
    setLoadingAssets(true);
    try {
      const data = await fetchGeneratedImageAssets();
      setLibraryAssets(data.items);
    } catch {
      message.error("素材加载失败");
      setLibraryAssets([]);
    } finally {
      setLoadingAssets(false);
    }
  }

  function pickAsset(asset: GeneratedImageAsset) {
    setAiBgUrl(asset.file_path);
    setUseAiBg(true);
    setPickerOpen(false);
    message.success("已选为封面插画");
    if (pages.length) {
      void renderPreview(styleId, layoutId, asset.file_path);
    }
  }

  return (
    <div>
      {!embedded ? (
        <PageHeader
          eyebrow="卡片工作室"
          title="卡片工坊"
          description="Markdown → 多页 PNG 卡片，4 种版式 × 10 套配色；正文只在本地渲染，保存到素材库时才上传图片。"
        />
      ) : null}
      <Row justify="end" align="middle" style={{ marginBottom: embedded ? 12 : 24 }}>
        <Col>
          <Space wrap>
            <Button
              onClick={() => {
                setMarkdown(SAMPLE_MARKDOWN);
                setDocumentTitle("3 个方法，普通人也能做出爆款笔记");
                setSubtitle("把长文变成适合小红书发布的多页卡片");
              }}
            >
              恢复示例
            </Button>
            <Button type="primary" icon={<PictureOutlined />} loading={generating} onClick={() => void renderPreview()}>
              生成预览
            </Button>
            <Button icon={<DownloadOutlined />} disabled={!pages.length} onClick={downloadAll}>
              下载全部 PNG
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={uploading}
              disabled={!pages.length || !draftId}
              title={draftId ? "把卡片写入草稿图片素材，不直接创建发布任务" : "先在下方选择要关联的草稿"}
              onClick={() => void attachCardsToDraft()}
            >
              加入草稿
            </Button>
            {attachedCount > 0 && draftId ? (
              <Button type="primary" ghost onClick={() => navigate("/platforms/xhs/write/drafts")}>
                去草稿工坊（已加入 {attachedCount} 张）
              </Button>
            ) : null}
            <Button icon={<PictureOutlined />} onClick={() => void openAssetPicker()}>
              从素材库选图
            </Button>
            <Button
              icon={<DatabaseOutlined />}
              loading={savingLibrary}
              disabled={!pages.length}
              onClick={() => void saveCardsToLibrary()}
              title="只存进图片素材，不关联任何草稿"
            >
              存为图片素材
            </Button>
          </Space>
        </Col>
      </Row>

      {draftId ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={`已关联草稿 #${draftId}：生成预览后点「加入草稿」，卡片会写入草稿图片素材；发布仍从草稿工坊送入发布中心。`}
        />
      ) : (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="当前是独立模式：可以下载 PNG 手动上传，或在下面选择一个草稿关联。"
          description={
            <Space wrap style={{ marginTop: 8 }}>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择要加入的草稿"
                style={{ width: 320 }}
                value={linkedDraftId ?? undefined}
                onChange={(value) => setLinkedDraftId(value ?? null)}
                options={draftOptions}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                关联后「加入草稿」才会写入这篇草稿的图片素材。
              </Text>
            </Space>
          }
        />
      )}

      <Row gutter={16}>
        <Col xs={24} lg={9}>
          <Card size="small" title="内容">
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <div>
                <Text strong style={{ display: "block", marginBottom: 4 }}>封面标题</Text>
                <Input value={documentTitle} onChange={(event) => setDocumentTitle(event.target.value)} maxLength={80} showCount />
              </div>
              <div>
                <Text strong style={{ display: "block", marginBottom: 4 }}>副标题</Text>
                <Input value={subtitle} onChange={(event) => setSubtitle(event.target.value)} maxLength={120} />
              </div>
              <div>
                <Text strong style={{ display: "block", marginBottom: 4 }}>版式</Text>
                <Select
                  value={layoutId}
                  onChange={handleLayoutChange}
                  style={{ width: "100%" }}
                  options={CARD_LAYOUTS.map((item) => ({ value: item.id, label: item.name }))}
                />
              </div>
              <div>
                <Text strong style={{ display: "block", marginBottom: 4 }}>配色</Text>
                <Select
                  value={styleId}
                  onChange={handleStyleChange}
                  style={{ width: "100%" }}
                  options={CARD_STYLES.map((item) => ({ value: item.id, label: item.name }))}
                />
                <Text type="secondary" style={{ fontSize: 11 }}>切换后会自动重新生成预览</Text>
              </div>
              <div>
                <Text strong style={{ display: "block", marginBottom: 4 }}>AI 封面插画（可选）</Text>
                <Space.Compact style={{ width: "100%" }}>
                  <Input
                    value={bgPrompt}
                    onChange={(event) => setBgPrompt(event.target.value)}
                    placeholder="描述想要的画面，如：早餐桌、咖啡、柔和自然光"
                    maxLength={300}
                  />
                  <Button
                    icon={<PictureOutlined />}
                    loading={bgGenerating}
                    onClick={() => void handleGenerateBackground()}
                  >
                    生成
                  </Button>
                </Space.Compact>
                <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
                  <Checkbox checked={useAiBg} onChange={(event) => setUseAiBg(event.target.checked)} disabled={!aiBgUrl}>
                    封面使用 AI 插画
                  </Checkbox>
                  {aiBgUrl && (
                    <img
                      src={aiBgUrl}
                      alt="AI 插画"
                      style={{ width: 36, height: 48, objectFit: "cover", borderRadius: 8, border: "1px solid rgba(127,127,127,.3)" }}
                    />
                  )}
                </div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  有图时作为封面画册插图，没有图时自动使用几何图形 + 章节看点排版。
                </Text>
              </div>
              <div>
                <Text strong style={{ display: "block", marginBottom: 4 }}>Markdown 正文</Text>
                <TextArea
                  value={markdown}
                  onChange={(event) => setMarkdown(event.target.value)}
                  autoSize={{ minRows: 20, maxRows: 40 }}
                  style={{ fontFamily: '"Cascadia Code", Consolas, monospace', fontSize: 13 }}
                />
              </div>
              <Space>
                <Button icon={<ReloadOutlined />} onClick={() => setPages([])}>清空预览</Button>
                <Text type="secondary" style={{ fontSize: 12 }}>支持标题、列表、引用、代码块</Text>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card
            size="small"
            title={`预览 ${pages.length ? `· ${pages.length} 页` : ""}`}
            extra={<Text type="secondary" style={{ fontSize: 12 }}>1080 × 1440</Text>}
          >
            {generating ? (
              <Spin size="large" style={{ display: "block", textAlign: "center", margin: "80px 0" }} />
            ) : pages.length ? (
              <Image.PreviewGroup>
                <Row gutter={[12, 12]}>
                  {pages.map((url, index) => (
                    <Col xs={12} md={8} xl={6} key={`${index}-${url.length}`}>
                      <div style={{ borderRadius: 8, overflow: "hidden", border: "1px solid rgba(127,127,127,.2)" }}>
                        <Image src={url} alt={`卡片 ${index + 1}`} style={{ width: "100%", display: "block" }} />
                        <div style={{ padding: "6px 8px", textAlign: "center" }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>第 {index + 1} 页</Text>
                        </div>
                      </div>
                    </Col>
                  ))}
                </Row>
              </Image.PreviewGroup>
            ) : (
              <Empty description="点击「生成预览」查看卡片效果" style={{ margin: "80px 0" }} />
            )}
            {pages.length ? (
              <Paragraph type="secondary" style={{ marginTop: 16, fontSize: 12 }}>
                预览图可直接右键保存；批量下载会生成每页独立的 PNG 文件。
              </Paragraph>
            ) : null}
          </Card>
        </Col>
      </Row>

      <Modal
        title="从素材库选择封面插画"
        open={pickerOpen}
        onCancel={() => setPickerOpen(false)}
        footer={null}
        width={760}
      >
        {loadingAssets ? (
          <Spin style={{ display: "block", textAlign: "center", padding: 32 }} />
        ) : libraryAssets.length === 0 ? (
          <Empty description="图片素材里还没有图片，可以先去「图片素材」页生成或上传" />
        ) : (
          <Row gutter={[12, 12]}>
            {libraryAssets.map((asset) => (
              <Col xs={12} sm={8} md={6} key={asset.id}>
                <div
                  onClick={() => pickAsset(asset)}
                  style={{
                    cursor: "pointer",
                    border: "1px solid rgba(127,127,127,.25)",
                    borderRadius: 8,
                    overflow: "hidden",
                  }}
                >
                  <Image
                    src={asset.file_path}
                    preview={false}
                    height={120}
                    style={{ width: "100%", objectFit: "cover" }}
                  />
                  <div style={{ padding: "4px 8px" }}>
                    <Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                      {asset.prompt || (asset.params?.kind === "card" ? "卡片" : "未命名")}
                    </Text>
                  </div>
                </div>
              </Col>
            ))}
          </Row>
        )}
      </Modal>

      <NextStepBar
        description="卡片已保存到素材库；回草稿工坊把它加进笔记，或去发布队列。"
        actions={[
          { label: "回草稿配图", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs" },
        ]}
      />
    </div>
  );
}
