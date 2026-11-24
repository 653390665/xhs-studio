/** Shared user-facing labels for task types and product concepts. */

export const TASK_TYPE_LABELS: Record<string, string> = {
  ai_rewrite: "AI 改写",
  ai_generate_note: "笔记生成",
  ai_generate_title: "标题生成",
  ai_generate_tags: "标签生成",
  ai_generate_from_images: "图片生成笔记",
  ai_polish_text: "文本润色",
  ai_image_generate: "配图生成",
  ai_image_generate_cover: "封面生成",
  ai_image_describe: "图片描述",
  crawl: "数据抓取",
  publish: "发布任务",
  creator_publish: "发布任务",
  creator_publish_retry: "发布重试",
  creator_publish_cancel: "取消发布",
  creator_publish_scheduler: "定时发布",
  auto_ops_run: "按关键词定时生成",
  export: "导出任务",
  monitoring_refresh: "监控刷新",
  monitoring_crawl: "监控采集",
};

export function taskTypeLabel(type: string): string {
  return TASK_TYPE_LABELS[type] ?? "未知任务";
}
