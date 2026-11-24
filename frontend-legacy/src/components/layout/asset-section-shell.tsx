import { ASSET_TOP_TABS } from "../../app/navigation";
import { SectionShell } from "./section-shell";

/**
 * Asset section now uses the same data-driven shell as every other section.
 * 洞察 pages are peers in ASSET_TOP_TABS; only 采集 renders a second row.
 */
export function AssetSectionShell() {
  return <SectionShell tabs={ASSET_TOP_TABS} />;
}
