import { DeleteOutlined, FileTextOutlined } from "@ant-design/icons";
import {
  Badge,
  Button,
  Card,
  Empty,
  List,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  theme,
  Typography,
} from "antd";
import { Link } from "react-router-dom";

import { formatShanghaiTime } from "../../../../lib/time";
import type { Draft } from "../../../../types";

const { Text, Paragraph } = Typography;

export type DraftReviewFilter = "all" | "pending" | "adopted" | "discarded";
export type DraftReadinessFilter = "all" | "ready" | "missing_media" | "missing_account";

const DRAFT_ORIGIN_LABELS: Record<string, string> = {
  manual: "手动",
  ai: "AI 生成",
  ai_image: "图片生成",
  topic: "选题转草稿",
  agent: "对话生成",
  matrix: "多账号版本",
  batch_rewrite: "批量改写",
  batch_create: "批量建草稿",
  douyin_import: "抖音蒸馏",
  auto_ops: "按关键词定时生成",
};

type DraftQueueProps = {
  drafts: Draft[];
  selectedDraftId: number | null;
  isLoading: boolean;
  reviewFilter: DraftReviewFilter;
  originFilter: string;
  readinessFilter: DraftReadinessFilter;
  onReviewFilterChange: (value: DraftReviewFilter) => void;
  onOriginFilterChange: (value: string) => void;
  onReadinessFilterChange: (value: DraftReadinessFilter) => void;
  onClearFilters: () => void;
  onGenerateNew: () => void;
  onSelect: (draft: Draft) => void;
  onDelete: (draftId: number) => void;
  onGoToImages: (draft: Draft) => void;
};

export function DraftQueue({
  drafts,
  selectedDraftId,
  isLoading,
  reviewFilter,
  originFilter,
  readinessFilter,
  onReviewFilterChange,
  onOriginFilterChange,
  onReadinessFilterChange,
  onClearFilters,
  onGenerateNew,
  onSelect,
  onDelete,
  onGoToImages,
}: DraftQueueProps) {
  const { token } = theme.useToken();
  const visibleDrafts = drafts.filter((draft) => {
    if (readinessFilter === "ready") {
      return draft.media_ready !== false && draft.account_ready !== false;
    }
    if (readinessFilter === "missing_media") return draft.media_ready === false;
    if (readinessFilter === "missing_account") return draft.account_ready === false;
    return true;
  });
  const filtersActive =
    reviewFilter !== "all" || originFilter !== "all" || readinessFilter !== "all";

  return (
    <Card
      title={
        <Space>
          <Text strong>草稿队列</Text>
          <Badge count={visibleDrafts.length} style={{ backgroundColor: token.colorPrimary }} />
        </Space>
      }
      styles={{ body: { padding: 0 } }}
    >
      <div style={{ padding: "10px 16px", borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
        <Space direction="vertical" size={6} style={{ width: "100%" }}>
          <Select
            size="small"
            value={reviewFilter}
            onChange={onReviewFilterChange}
            style={{ width: "100%" }}
            options={[
              { value: "all", label: "全部草稿" },
              { value: "pending", label: "待审" },
              { value: "adopted", label: "已采用" },
              { value: "discarded", label: "已废弃" },
            ]}
          />
          <Select
            size="small"
            value={originFilter}
            onChange={onOriginFilterChange}
            style={{ width: "100%" }}
            options={[
              { value: "all", label: "全部来源" },
              { value: "manual", label: "手动" },
              { value: "topic", label: "选题转草稿" },
              { value: "agent", label: "对话生成" },
              { value: "ai", label: "AI 生成" },
              { value: "ai_image", label: "图片生成" },
              { value: "douyin_import", label: "抖音蒸馏" },
              { value: "matrix", label: "多账号版本" },
              { value: "batch_rewrite", label: "批量改写" },
              { value: "batch_create", label: "批量建草稿" },
              { value: "auto_ops", label: "按关键词定时生成" },
            ]}
          />
          <Select
            size="small"
            value={readinessFilter}
            onChange={onReadinessFilterChange}
            style={{ width: "100%" }}
            options={[
              { value: "all", label: "全部就绪状态" },
              { value: "ready", label: "可送发布" },
              { value: "missing_media", label: "缺图" },
              { value: "missing_account", label: "缺账号" },
            ]}
          />
        </Space>
      </div>
      {isLoading ? (
        <div style={{ textAlign: "center", padding: 32 }}>
          <Spin />
          <Paragraph type="secondary" style={{ marginTop: 12 }}>正在加载草稿...</Paragraph>
        </div>
      ) : visibleDrafts.length === 0 ? (
        <Empty
          image={<FileTextOutlined style={{ fontSize: 40, color: token.colorTextTertiary }} />}
          imageStyle={{ height: 56 }}
          description={
            <div>
              <Paragraph type="secondary">
                {filtersActive ? "没有符合当前筛选的草稿。" : "还没有可编辑草稿。"}
              </Paragraph>
              {filtersActive ? (
                <Button size="small" onClick={onClearFilters}>
                  清除筛选
                </Button>
              ) : (
                <Space wrap>
                  <Button type="primary" size="small" onClick={onGenerateNew}>
                    生成新草稿
                  </Button>
                  <Link to="/platforms/xhs/plan">
                    <Button size="small">去选题库</Button>
                  </Link>
                  <Link to="/platforms/xhs/assets/library">
                    <Button size="small">去样本库</Button>
                  </Link>
                </Space>
              )}
            </div>
          }
          style={{ padding: 24 }}
        />
      ) : (
        <List
          dataSource={visibleDrafts}
          renderItem={(draft) => {
            const isActive = draft.id === selectedDraftId;
            return (
              <List.Item
                onClick={() => onSelect(draft)}
                style={{
                  cursor: "pointer",
                  padding: "10px 16px",
                  background: isActive ? token.colorPrimaryBg : "transparent",
                  borderLeft: isActive ? `2px solid ${token.colorPrimary}` : "2px solid transparent",
                  transition: "all 0.15s",
                  margin: 0,
                }}
              >
                <div style={{ minWidth: 0, width: "100%", display: "flex", alignItems: "center", gap: 4 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text
                      ellipsis
                      style={{
                        display: "block",
                        fontSize: 13,
                        fontWeight: isActive ? 600 : 400,
                      }}
                    >
                      {draft.title || "未命名草稿"}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {formatShanghaiTime(draft.created_at)}
                    </Text>
                    {draft.review_status === "adopted" ? <Tag color="blue" style={{ marginLeft: 4 }}>已采用</Tag> : null}
                    {draft.review_status === "discarded" ? <Tag style={{ marginLeft: 4 }}>已废弃</Tag> : null}
                    {!draft.review_status || draft.review_status === "pending" ? (
                      <Tag color="gold" style={{ marginLeft: 4 }}>待审</Tag>
                    ) : null}
                    {draft.origin && draft.origin !== "manual" ? (
                      <Tag color="purple" style={{ marginLeft: 4 }}>
                        {DRAFT_ORIGIN_LABELS[draft.origin] ?? draft.origin}
                      </Tag>
                    ) : null}
                    {draft.media_ready === false ? (
                      <Tag color="red" style={{ marginLeft: 4 }}>缺图</Tag>
                    ) : null}
                    {draft.account_ready === false ? (
                      <Tag color="orange" style={{ marginLeft: 4 }}>缺账号</Tag>
                    ) : null}
                  </div>
                  {draft.media_ready === false ? (
                    <Button
                      type="link"
                      size="small"
                      style={{ flexShrink: 0 }}
                      onClick={(event) => {
                        event.stopPropagation();
                        onGoToImages(draft);
                      }}
                    >
                      去配图
                    </Button>
                  ) : null}
                  <Popconfirm
                    title="删除此草稿？"
                    onConfirm={(event) => {
                      event?.stopPropagation();
                      onDelete(draft.id);
                    }}
                    onCancel={(event) => event?.stopPropagation()}
                  >
                    <Button
                      type="text"
                      danger
                      size="small"
                      icon={<DeleteOutlined />}
                      onClick={(event) => event.stopPropagation()}
                      style={{ flexShrink: 0 }}
                    />
                  </Popconfirm>
                </div>
              </List.Item>
            );
          }}
          style={{ maxHeight: "calc(100vh - 380px)", overflowY: "auto" }}
        />
      )}
    </Card>
  );
}
