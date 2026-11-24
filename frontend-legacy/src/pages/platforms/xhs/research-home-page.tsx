import {
  CloudDownloadOutlined,
  DatabaseOutlined,
  FireOutlined,
  LineChartOutlined,
  TagsOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  List,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import { fetchSavedNotes } from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type { SavedNote } from "../../../types";

const { Text, Paragraph } = Typography;

const RESEARCH_ENTRIES = [
  {
    key: "library",
    title: "样本库",
    description: "已采集的外部笔记；低粉高赞、互动和标签筛选，选中 3 篇以上可直接蒸馏成 Skill。",
    to: "/platforms/xhs/assets/library",
    icon: <DatabaseOutlined />,
  },
  {
    key: "collect",
    title: "采集",
    description: "搜索或批量抓取外部笔记，补全正文、图片和互动数据。",
    to: "/platforms/xhs/assets/collect",
    icon: <CloudDownloadOutlined />,
  },
  {
    key: "keywords",
    title: "热词追踪",
    description: "维护赛道、选题和品牌关键词，观察外部样本的命中量与每日涨跌。",
    to: "/platforms/xhs/assets/keywords",
    icon: <TagsOutlined />,
  },
  {
    key: "trends",
    title: "榜单与趋势",
    description: "爆款榜、黑马榜和热搜词，找当下值得拆的样本。",
    to: "/platforms/xhs/assets/trends",
    icon: <FireOutlined />,
  },
  {
    key: "analysis",
    title: "对标分析",
    description: "监控目标和相似账号，全部围绕外部账号。",
    to: "/platforms/xhs/assets/analysis",
    icon: <LineChartOutlined />,
  },
  {
    key: "douyin",
    title: "抖音口播提取",
    description: "从抖音口播蒸馏写法；产物落在「提炼 → 创作 Skill」。",
    to: "/platforms/xhs/assets/douyin",
    icon: <VideoCameraOutlined />,
  },
];

export function ResearchHomePage() {
  const [samples, setSamples] = useState<SavedNote[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await fetchSavedNotes({
          platform: "xhs",
          page_size: 8,
          sort_by: "created_at",
          source: "library",
        });
        if (cancelled) return;
        setSamples(result.items);
        setLoadError(null);
      } catch {
        if (cancelled) return;
        setSamples([]);
        setLoadError("最近样本加载失败，可能是接口问题；不代表样本库为空。");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return (
    <div>
      <PageHeader
        eyebrow="素材"
        title="素材首页"
        description="这里放所有「向外找」的输入：样本、榜单、热词和对标账号。学到的写法去「提炼」，自己的发布表现去「总览 → 复盘」。"
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="素材看外面，复盘看自己"
        description="样本库、榜单、热词和对标都属于外部输入；自己的发布数据统一去「总览 → 复盘」。选中 3 篇以上样本可以蒸馏成 Skill。"
      />

      {loadError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={loadError}
          action={
            <Button size="small" onClick={() => setReloadKey((value) => value + 1)}>
              重试
            </Button>
          }
        />
      ) : null}

      <Row gutter={[16, 16]}>
        {RESEARCH_ENTRIES.map((entry) => (
          <Col xs={24} sm={12} lg={8} key={entry.key}>
            <Card
              hoverable
              style={{ height: "100%" }}
              actions={[
                <Link to={entry.to} key="open">
                  <Button type="link">进入{entry.title}</Button>
                </Link>,
              ]}
            >
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Space>
                  <span style={{ fontSize: 22 }}>{entry.icon}</span>
                  <Text strong>{entry.title}</Text>
                </Space>
                <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
                  {entry.description}
                </Paragraph>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        style={{ marginTop: 16 }}
        title="最近入库样本"
        extra={<Link to="/platforms/xhs/assets/library">查看全部</Link>}
      >
        {samples.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="样本库还没有样本" />
        ) : (
          <List
            size="small"
            dataSource={samples}
            renderItem={(note) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Link
                      to={`/platforms/xhs/assets/library?q=${encodeURIComponent(note.note_id)}`}
                    >
                      <Text style={{ fontSize: 13 }} ellipsis>
                        {note.title || note.note_id}
                      </Text>
                    </Link>
                  }
                  description={
                    <Space wrap size={4}>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {note.author_name || "未知作者"}
                      </Text>
                      <Tag>
                        互动{" "}
                        {(note.likes || 0) +
                          (note.collects || 0) +
                          (note.comments || 0) +
                          (note.shares || 0)}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {formatShanghaiTime(note.created_at)}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <NextStepBar
        description="样本入库后先选 3 篇以上有正文的样本，再蒸馏写法或去选题；样本不足时可以直接写通用草稿。"
        actions={[
          { label: "去样本库", to: "/platforms/xhs/assets/library" },
          { label: "去提炼", to: "/platforms/xhs/refine", primary: true },
        ]}
      />
    </div>
  );
}
