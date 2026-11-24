import { UserOutlined } from "@ant-design/icons";
import {
  Avatar,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  List,
  Popconfirm,
  Row,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useState } from "react";

import { distillAuthorStyle, findSimilarAccounts } from "../../lib/api";
import type { SimilarAccountsResult } from "../../lib/api";

const { Text } = Typography;

/**
 * 外部相似账号：只做对标参考，不参与自己的数据统计。
 * 放在「素材 → 对标分析」，我的复盘不再承载这块。
 *
 * 每个账号可以「蒸馏风格」：采集它最近的笔记、抓正文、蒸馏成 Skill。
 * 这是把「发现账号」和「学写法」连起来的那一步，之前要手动搬三个页面。
 */
export function SimilarAccountsCard() {
  const [keyword, setKeyword] = useState("");
  const [seedFans, setSeedFans] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimilarAccountsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [distilling, setDistilling] = useState<string | null>(null);

  async function handleFind() {
    const trimmed = keyword.trim();
    if (!trimmed) {
      setError("先输入一个关键词，例如「通勤穿搭」「咖啡」。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setResult(
        await findSimilarAccounts({
          keyword: trimmed,
          seed_fans: seedFans ?? 0,
          limit: 6,
        }),
      );
    } catch (requestError) {
      const detail = (requestError as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail || "相似账号查询失败，请确认账号登录态有效。");
    } finally {
      setLoading(false);
    }
  }

  async function handleDistill(account: { user_id: string; nickname: string }) {
    const trimmed = keyword.trim();
    if (!trimmed) {
      setError("蒸馏需要关键词，用来定位这个账号的内容。");
      return;
    }
    setDistilling(account.user_id);
    setError(null);
    try {
      const profile = await distillAuthorStyle({
        author_id: account.user_id,
        author_name: account.nickname,
        keyword: trimmed,
        max_notes: 6,
      });
      message.success(
        `已蒸馏「${profile.name}」：用了 ${profile.collected_notes} 篇笔记。去「提炼 → 创作 Skill」查看。`,
      );
      if (profile.skipped_notes) {
        message.info(`另有 ${profile.skipped_notes} 篇被跳过（限流或已删除）。`);
      }
    } catch (requestError) {
      const detail = (requestError as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail || "蒸馏失败，请确认登录态和默认文本模型。");
    } finally {
      setDistilling(null);
    }
  }

  return (
    <Card
      title="相似账号推荐（外部对标）"
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          按关键词找同赛道账号，不计入自己的统计
        </Text>
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onPressEnter={() => void handleFind()}
          placeholder="关键词，如 通勤穿搭 / 咖啡"
          style={{ width: 260 }}
        />
        <InputNumber
          value={seedFans}
          onChange={(value) => setSeedFans(value)}
          placeholder="你的粉丝数（可选）"
          min={0}
          style={{ width: 180 }}
        />
        <Button type="primary" loading={loading} onClick={() => void handleFind()}>
          找相似账号
        </Button>
      </Space>

      {error ? (
        <Text type="danger" style={{ display: "block", fontSize: 12, marginBottom: 12 }}>
          {error}
        </Text>
      ) : null}

      {result ? (
        result.peer.length || result.benchmark.length ? (
          <Row gutter={[16, 16]}>
            {(
              [
                ["同阶对标", result.peer, "green"],
                ["高阶标杆", result.benchmark, "gold"],
              ] as const
            ).map(([label, accounts, color]) => (
              <Col xs={24} lg={12} key={label}>
                <Text strong>{label}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                  {accounts.length} 个
                </Text>
                <List
                  size="small"
                  dataSource={accounts}
                  locale={{ emptyText: "没有匹配到账号" }}
                  renderItem={(account) => (
                    <List.Item
                      actions={[
                        <Popconfirm
                          key="distill"
                          title={`蒸馏 ${account.nickname || "该账号"} 的写法`}
                          description="会采集它最近的笔记并生成「模仿 XX」Skill，需要几分钟。"
                          onConfirm={() =>
                            void handleDistill({
                              user_id: account.user_id,
                              nickname: account.nickname,
                            })
                          }
                        >
                          <Button
                            size="small"
                            type="link"
                            loading={distilling === account.user_id}
                          >
                            蒸馏写法
                          </Button>
                        </Popconfirm>,
                        <Button
                          key="open"
                          size="small"
                          type="link"
                          onClick={() =>
                            window.open(
                              `https://www.xiaohongshu.com/user/profile/${account.user_id}`,
                              "_blank",
                              "noopener",
                            )
                          }
                        >
                          主页
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        avatar={<Avatar src={account.avatar} icon={<UserOutlined />} />}
                        title={
                          <Space size={6}>
                            <Text style={{ fontSize: 13 }}>{account.nickname || "未命名"}</Text>
                            <Tag color={color} style={{ marginInlineEnd: 0 }}>
                              {account.fans_ratio}x
                            </Tag>
                          </Space>
                        }
                        description={
                          <span style={{ fontSize: 12 }}>
                            粉丝 {account.fans.toLocaleString()} · 平均互动{" "}
                            {Math.round(account.avg_engagement ?? 0)} · {account.reason}
                          </span>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Col>
            ))}
          </Row>
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="没有找到可比对的账号，换个关键词试试"
          />
        )
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          输入关键词后，会按粉丝量级和互动找出同赛道账号。
        </Text>
      )}
    </Card>
  );
}
