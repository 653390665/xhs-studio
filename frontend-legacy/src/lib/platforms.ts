import type { PlatformMeta } from "../types";

// Product surface today is XHS-only. The API registry may keep future
// platforms for planning, but the frontend must not advertise workspaces that
// do not exist yet.
export const fallbackPlatforms: PlatformMeta[] = [
  { id: "xhs", name_cn: "小红书", name_en: "XiaoHongShu", enabled: true, status: "enabled", accent_color: "#ff2442", icon: "xhs" },
];

export function getPlatform(id: string | undefined) {
  return fallbackPlatforms.find((platform) => platform.id === id) ?? fallbackPlatforms[0];
}
