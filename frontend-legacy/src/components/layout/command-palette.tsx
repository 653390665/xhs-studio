import { Empty, Input, List, Modal, Tag, theme, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { NAV_SECTIONS } from "../../app/navigation";
import type { SectionTab } from "../../app/navigation";

const { Text } = Typography;

type CommandItem = {
  key: string;
  label: string;
  group: string;
  to: string;
};

function collectTabItems(
  items: CommandItem[],
  group: string,
  tabs: SectionTab[],
  prefix: string[] = [],
): void {
  for (const tab of tabs) {
    const labels = [...prefix, tab.label];
    if (tab.children?.length) {
      collectTabItems(items, group, tab.children, labels);
      continue;
    }
    items.push({
      key: tab.key,
      label: labels.join(" / "),
      group,
      to: tab.key,
    });
  }
}

function buildCommandItems(): CommandItem[] {
  const items: CommandItem[] = [];

  for (const section of NAV_SECTIONS) {
    if (section.tabs.length === 0) {
      items.push({
        key: section.key,
        label: section.label,
        group: section.label,
        to: section.key,
      });
      continue;
    }
    collectTabItems(items, section.label, section.tabs);
  }

  return items;
}

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
};

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const items = useMemo(buildCommandItems, []);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return items;
    return items.filter((item) =>
      `${item.group} ${item.label} ${item.to}`.toLowerCase().includes(keyword),
    );
  }, [items, query]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIndex(0);
    }
  }, [open]);

  function choose(item: CommandItem | undefined) {
    if (!item) return;
    navigate(item.to);
    onClose();
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
      title="快速导航"
      destroyOnHidden
    >
      <Input
        autoFocus
        allowClear
        value={query}
        placeholder="搜索导航，例如：抖音、发布、Skill"
        onChange={(event) => {
          setQuery(event.target.value);
          setActiveIndex(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActiveIndex((index) => Math.min(index + 1, Math.max(filtered.length - 1, 0)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((index) => Math.max(index - 1, 0));
          } else if (event.key === "Enter") {
            event.preventDefault();
            choose(filtered[activeIndex]);
          }
        }}
      />

      <div style={{ marginTop: 12, maxHeight: 420, overflowY: "auto" }}>
        {filtered.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的导航" />
        ) : (
          <List
            size="small"
            dataSource={filtered}
            renderItem={(item, index) => (
              <List.Item
                onClick={() => choose(item)}
                onMouseEnter={() => setActiveIndex(index)}
                style={{
                  cursor: "pointer",
                  borderRadius: 8,
                  paddingInline: 12,
                  background: index === activeIndex ? token.colorPrimaryBg : "transparent",
                }}
              >
                <List.Item.Meta
                  title={<Text>{item.label}</Text>}
                  description={<Text type="secondary" style={{ fontSize: 11 }}>{item.to}</Text>}
                />
                <Tag color="blue">{item.group}</Tag>
              </List.Item>
            )}
          />
        )}
      </div>
      <Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 11 }}>
        ↑↓ 选择 · Enter 打开 · Esc 关闭 · Ctrl/⌘ + K 随时呼出
      </Text>
    </Modal>
  );
}
