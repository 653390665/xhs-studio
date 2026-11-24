import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  List,
  Popconfirm,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  createKeywordGroup,
  deleteKeywordGroup,
  fetchKeywordGroup,
  fetchKeywordGroups,
  updateKeywordGroup,
} from "../../../lib/api";
import type { KeywordGroup, KeywordGroupDetail } from "../../../types";

const { Text } = Typography;

function splitKeywords(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((keyword) => keyword.trim())
    .filter(Boolean);
}

function joinKeywords(keywords: string[]): string {
  return keywords.join("，");
}

export function XhsKeywordsPage() {
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [groups, setGroups] = useState<KeywordGroup[]>([]);
  const [detailsByGroup, setDetailsByGroup] = useState<
    Record<number, KeywordGroupDetail>
  >({});
  const [name, setName] = useState("");
  const [keywords, setKeywords] = useState("");
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isWorking, setIsWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadGroups() {
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchKeywordGroups("xhs");
      setGroups(result.items);
      const details = await Promise.all(
        result.items.map(async (group) => {
          try {
            return [group.id, await fetchKeywordGroup(group.id)] as const;
          } catch {
            return [group.id, undefined] as const;
          }
        })
      );
      setDetailsByGroup(
        Object.fromEntries(
          details.filter(
            (entry): entry is readonly [number, KeywordGroupDetail] =>
              Boolean(entry[1])
          )
        )
      );
    } catch {
      setError("关键词组加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadGroups();
  }, []);

  function resetForm() {
    setEditingGroupId(null);
    setName("");
    setKeywords("");
  }

  function editGroup(group: KeywordGroup) {
    setEditingGroupId(group.id);
    setName(group.name);
    setKeywords(joinKeywords(group.keywords));
  }

  async function saveGroup() {
    const nextKeywords = splitKeywords(keywords);
    if (!name.trim() || nextKeywords.length === 0) {
      message.warning("请填写名称和至少一个关键词。");
      return;
    }
    setIsWorking(true);
    try {
      if (editingGroupId) {
        const updated = await updateKeywordGroup(editingGroupId, {
          name: name.trim(),
          keywords: nextKeywords,
        });
        setGroups((currentGroups) =>
          currentGroups.map((group) =>
            group.id === updated.id ? updated : group
          )
        );
        const detail = await fetchKeywordGroup(updated.id);
        setDetailsByGroup((currentDetails) => ({
          ...currentDetails,
          [updated.id]: detail,
        }));
        message.success("关键词组已更新。");
      } else {
        const created = await createKeywordGroup({
          platform: "xhs",
          name: name.trim(),
          keywords: nextKeywords,
        });
        setGroups((currentGroups) => [created, ...currentGroups]);
        const detail = await fetchKeywordGroup(created.id);
        setDetailsByGroup((currentDetails) => ({
          ...currentDetails,
          [created.id]: detail,
        }));
        message.success("关键词组已创建。");
      }
      resetForm();
    } catch {
      message.error("关键词组保存失败。");
    } finally {
      setIsWorking(false);
    }
  }

  async function removeGroup(groupId: number) {
    setIsWorking(true);
    try {
      await deleteKeywordGroup(groupId);
      setGroups((currentGroups) =>
        currentGroups.filter((group) => group.id !== groupId)
      );
      setDetailsByGroup((currentDetails) => {
        const nextDetails = { ...currentDetails };
        delete nextDetails[groupId];
        return nextDetails;
      });
      if (editingGroupId === groupId) {
        resetForm();
      }
      message.success("关键词组已删除。");
    } catch {
      message.error("关键词组删除失败。");
    } finally {
      setIsWorking(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="热词追踪"
        title="热词追踪"
        description="维护选题、赛道和品牌关键词组，统计它们在样本库里的命中量与互动机会；每次打开本页会记录当天快照，标签上的 ± 是与上一次记录的差值。"
        action={
          <Button
            icon={<ReloadOutlined />}
            disabled={isLoading}
            onClick={loadGroups}
          >
            刷新
          </Button>
        }
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="热词追踪只看外部样本"
        description="命中量和互动只统计样本库里的外部笔记；自己的关键词表现去「总览 → 复盘」。"
      />

      <Card
        style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary, marginBottom: 24 }}
      >
        <Form layout="inline" style={{ flexWrap: "wrap", gap: 8 }}>
          <Form.Item>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="关键词组名称"
              disabled={isLoading}
              style={{ width: 200 }}
            />
          </Form.Item>
          <Form.Item>
            <Input.TextArea
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="关键词，用逗号或换行分隔"
              disabled={isLoading}
              autoSize={{ minRows: 1, maxRows: 3 }}
              style={{ width: 320 }}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              icon={editingGroupId ? <SaveOutlined /> : <PlusOutlined />}
              disabled={isWorking}
              onClick={() => void saveGroup()}
            >
              {editingGroupId ? "保存修改" : "创建组"}
            </Button>
          </Form.Item>
          {editingGroupId && (
            <Form.Item>
              <Button disabled={isWorking} onClick={resetForm}>
                取消
              </Button>
            </Form.Item>
          )}
        </Form>
      </Card>

      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}

      {isLoading ? (
        <div style={{ textAlign: "center", padding: 48 }}>
          <Spin tip="正在加载关键词组..." />
        </div>
      ) : groups.length === 0 ? (
        <Card style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary }}>
          <Empty description="暂无关键词组。先建一组词，再去搜索样本。" />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {groups.map((group) => {
            const detail = detailsByGroup[group.id];
            return (
              <Col xs={24} md={12} key={group.id}>
                <Card
                  title={
                    <Space>
                      <Text strong>{group.name}</Text>
                      <Tag color="blue">xhs</Tag>
                    </Space>
                  }
                  style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary }}
                >
                  <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
                    {joinKeywords(group.keywords)}
                  </Text>

                  <Button
                    size="small"
                    icon={<SearchOutlined />}
                    style={{ marginBottom: 12 }}
                    disabled={!group.keywords.length}
                    onClick={() =>
                      navigate(
                        `/platforms/xhs/assets/collect?keyword=${encodeURIComponent(
                          group.keywords.slice(0, 6).join(","),
                        )}`,
                      )
                    }
                  >
                    用这组词去搜索样本
                  </Button>

                  <Row gutter={16} style={{ marginBottom: 16 }}>
                    <Col span={8}>
                      <Statistic
                        title="命中"
                        value={detail?.trend.total_matches ?? 0}
                        suffix="条"
                        valueStyle={{ fontSize: 16 }}
                      />
                    </Col>
                    <Col span={8}>
                      <Statistic
                        title="互动"
                        value={detail?.trend.total_engagement ?? 0}
                        valueStyle={{ fontSize: 16 }}
                      />
                    </Col>
                    <Col span={8}>
                      <Statistic
                        title="关键词"
                        value={group.keywords.length}
                        suffix="个"
                        valueStyle={{ fontSize: 16 }}
                      />
                    </Col>
                  </Row>

                  {detail?.trend.keywords.length ? (
                    <div
                      style={{
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 8,
                        marginBottom: 16,
                      }}
                    >
                      {detail.trend.keywords.map((kw) => {
                        const trend = kw.trend;
                        const delta = kw.notes_delta;
                        return (
                          <Tag
                            key={kw.keyword}
                            color={
                              trend === "up"
                                ? "green"
                                : trend === "down"
                                  ? "red"
                                  : trend === "new"
                                    ? "blue"
                                    : undefined
                            }
                            title={
                              trend === "new"
                                ? "首次记录，明天开始就能显示涨跌"
                                : kw.last_seen
                                  ? `对比 ${kw.last_seen}`
                                  : undefined
                            }
                          >
                            {kw.keyword} · {kw.notes} 条
                            {trend === "new" ? " · 新增" : null}
                            {typeof delta === "number" && delta !== 0
                              ? ` · ${delta > 0 ? "+" : ""}${delta}`
                              : null}
                          </Tag>
                        );
                      })}
                    </div>
                  ) : null}

                  {detail?.trend.matched_notes.length ? (
                    <List
                      size="small"
                      dataSource={detail.trend.matched_notes.slice(0, 3)}
                      style={{ marginBottom: 16 }}
                      renderItem={(note) => (
                        <List.Item>
                          <List.Item.Meta
                            title={note.title || note.note_id}
                            description={`${note.author_name || "未知作者"} · 互动 ${note.engagement}`}
                          />
                        </List.Item>
                      )}
                    />
                  ) : null}

                  <Space>
                    <Button
                      icon={<EditOutlined />}
                      disabled={isWorking}
                      onClick={() => editGroup(group)}
                    >
                      编辑
                    </Button>
                    <Popconfirm
                      title="删除这个关键词组？"
                      description="删除后组内的关键词不会自动加入其它组。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => removeGroup(group.id)}
                    >
                      <Button
                        icon={<DeleteOutlined />}
                        danger
                        disabled={isWorking}
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      <NextStepBar
        description="关键词组用于采集和对标；下一步去选题库，或把样本沉淀到样本库。"
        actions={[
          { label: "去选题库", to: "/platforms/xhs/plan", primary: true },
          { label: "去样本库", to: "/platforms/xhs/assets/library" },
        ]}
      />
    </div>
  );
}
