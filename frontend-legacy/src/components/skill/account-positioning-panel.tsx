import { Alert, Button, Card, Col, Empty, Form, Input, Row, Space, Spin, Tag, Typography, message } from "antd";
import { ReloadOutlined, SaveOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";

import {
  fetchAccountPositioning,
  fetchPositioningPromptBlock,
  saveAccountPositioning,
  type AccountPositioning,
} from "../../lib/api";
const { Text, Paragraph } = Typography;

const FIELD_LABELS: Record<string, string> = {
  positioning: "一句话定位",
  audience: "目标用户",
  promise: "内容承诺",
  main_topics: "内容支柱",
  taboos: "禁区",
  language_samples: "语言样本",
};

/**
 * 账号定位面板。
 *
 * 刻意与「风格」分开：风格需要语料才能蒸馏出来，早期账号还没有语料，
 * 但定位从第一天就该有。定位会独立注入写稿，不依赖任何生效风格。
 *
 * 「实际注入内容」区块展示的是后端真正拼进 prompt 的文本，不是这里的表单
 * 复述——否则界面又在描述一个不存在的系统。
 */
export function AccountPositioningPanel({ accountId }: { accountId?: number | null }) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState<AccountPositioning | null>(null);
  const [block, setBlock] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [positioning, promptBlock] = await Promise.all([
        fetchAccountPositioning(accountId),
        fetchPositioningPromptBlock(accountId),
      ]);
      setData(positioning);
      setBlock(promptBlock.prompt_block);
      form.setFieldsValue({
        positioning: positioning.positioning,
        audience: positioning.audience,
        promise: positioning.promise,
        main_topics: positioning.main_topics,
        taboos: positioning.taboos,
        language_samples: positioning.language_samples,
      });
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "读取账号定位失败";
      message.error(detail);
    } finally {
      setLoading(false);
    }
  }, [accountId, form]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    try {
      const values = await form.validateFields();
      const saved = await saveAccountPositioning(
        {
          positioning: values.positioning ?? "",
          audience: values.audience ?? "",
          promise: values.promise ?? "",
          main_topics: values.main_topics ?? [],
          taboos: values.taboos ?? [],
          language_samples: values.language_samples ?? [],
        },
        accountId,
      );
      setData(saved);
      const promptBlock = await fetchPositioningPromptBlock(accountId);
      setBlock(promptBlock.prompt_block);
      message.success("已保存。写稿时会按上面的定位执行。");
    } catch (error) {
      if ((error as { errorFields?: unknown }).errorFields) {
        return;
      }
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "保存失败";
      message.error(detail);
    } finally {
      setSaving(false);
    }
  }

  // The Form must stay mounted: calling useForm() without a connected <Form>
  // logs a warning and, worse, form.validateFields() resolves against nothing
  // during the first paint. Spin wraps it instead of replacing it.
  const missing = data?.missing ?? [];

  return (
    <Spin spinning={loading}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="定位不是写法，早期也不需要写法"
        description="写法要从一批已完成内容里蒸馏，账号没跑起来之前蒸不出来。定位是现在就该定下的东西：你帮谁、解决什么、绝不写什么。它会独立注入每一篇稿子。"
      />

      <Row gutter={16}>
        <Col xs={24} lg={15}>
          <Card
            title="账号定位"
            extra={
              <Space>
                <Button icon={<ReloadOutlined />} onClick={() => void load()}>
                  刷新
                </Button>
                <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={() => void save()}>
                  保存
                </Button>
              </Space>
            }
          >
            <Form form={form} layout="vertical">
              <Form.Item
                name="positioning"
                label={FIELD_LABELS.positioning}
                extra="一句话说清你是谁、做什么。例：宁波一人公司，用 AI 做真实交付。"
              >
                <Input.TextArea rows={2} placeholder="宁波一人公司，用 AI 做真实交付" />
              </Form.Item>
              <Form.Item
                name="audience"
                label={FIELD_LABELS.audience}
                extra="越具体越好。写「宁波本地想把 AI 用进业务的人」比写「AI 爱好者」有用。"
              >
                <Input.TextArea rows={2} placeholder="宁波本地想把 AI 用进业务的人" />
              </Form.Item>
              <Form.Item
                name="promise"
                label={`${FIELD_LABELS.promise}（不注入写稿）`}
                extra="帮谁、在什么场景、解决什么问题、为什么是你。它决定写什么选题，但不会进单篇稿子的 prompt——否则每篇都会变成销售稿。"
              >
                <Input.TextArea rows={2} placeholder="帮你在 90 天内跑通第一个 AI 交付单" />
              </Form.Item>
              <Form.Item
                name="main_topics"
                label={FIELD_LABELS.main_topics}
                extra="能持续写的方向，一行一个。建议 3-5 个。"
              >
                <Input.TextArea rows={3} placeholder={"AI 工具实测\n一人公司运营\n沙龙复盘"} />
              </Form.Item>
              <Form.Item
                name="taboos"
                label={`${FIELD_LABELS.taboos}（绝不写）`}
                extra="一行一个。这是最该先填的一项：不写禁区，模型就会替你承诺收益。"
              >
                <Input.TextArea rows={3} placeholder={"不承诺收益\n不编造嘉宾和案例"} />
              </Form.Item>
              <Form.Item
                name="language_samples"
                label={`${FIELD_LABELS.language_samples}（5-10 句真实原话）`}
                extra="你自己真会说的话，一行一句。这是原话素材，不是写法模仿；如果还没有，先留空。"
              >
                <Input.TextArea rows={4} placeholder={"我这两天被一个问题卡住了\n说句实话，我也不确定"} />
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={9}>
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Card title="还缺什么" size="small">
              {missing.length === 0 ? (
                <Text type="success">六项都填好了。</Text>
              ) : (
                <Space size={[6, 6]} wrap>
                  {missing.map((field: string) => (
                    <Tag key={field} color="warning">
                      {FIELD_LABELS[field] || field}
                    </Tag>
                  ))}
                </Space>
              )}
              <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
                缺「定位 / 目标用户」时，写稿会被要求不要编造人群和经历，而不是自由发挥。
              </Paragraph>
            </Card>

            <Card title="实际注入写稿的内容" size="small">
              {block ? (
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontSize: 12,
                    margin: 0,
                    opacity: 0.85,
                  }}
                >
                  {block}
                </pre>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={<Text type="secondary">还没有定位，写稿时不会注入任何账号身份</Text>}
                />
              )}
              <Paragraph type="secondary" style={{ fontSize: 11, marginTop: 10, marginBottom: 0 }}>
                这里显示的是后端真正拼进 prompt 的文本。内容承诺（promise）不会出现在这里，这是刻意的。
              </Paragraph>
            </Card>
          </Space>
        </Col>
      </Row>
    </Space>
    </Spin>
  );
}
