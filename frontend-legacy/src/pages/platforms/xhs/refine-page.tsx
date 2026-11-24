import { Alert, Card, Col, Row, Space, Tag, Typography } from "antd";
import { ExperimentOutlined, FileTextOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";

import { Term } from "../../../components/common/term";
import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";

const { Text, Paragraph } = Typography;

const REFINE_ENTRIES = [
  {
    key: "template",
    title: "结构模板",
    description: "位置结构按开头/中段/结尾统计；标题/要点模板给标题公式、要点顺序、关键词、CTA。",
    to: "/platforms/xhs/refine/templates",
    icon: <FileTextOutlined />,
    note: "管单篇",
  },
  {
    key: "skill",
    title: "创作 Skill",
    description:
      "3 篇以上样本蒸馏出的长期写法：读者、语气、工作流、分段写法、禁区。账号定位在「证据与定位」里独立维护，不覆盖 Skill。",
    to: "/platforms/xhs/refine/skills",
    icon: <ExperimentOutlined />,
    note: "管长期",
  },
];

/**
 * 提炼区首页：只做导航，不重复渲染子页面。
 *
 * 这个区只回答「怎么写」。回答「写什么」的选题库在「选题」区。
 *
 * 账号定位没有合并进 Skill：定位从第一天就该有，Skill 需要样本才能蒸馏；
 * 两者职责不同，生成时同时注入，冲突时以定位/禁区为准。
 */
export function RefinePage() {
  return (
    <div>
      <PageHeader
        eyebrow="提炼"
        title="提炼首页"
        description={
          <>
            把「向外学」的结果固化成可复用的写法：模板管单篇骨架，
            <Term k="skill">Skill</Term> 管长期表达；账号定位是独立透明层。
          </>
        }
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Skill 管长期写法，账号定位是独立透明层"
        description={
          <Text type="secondary" style={{ fontSize: 12 }}>
            账号定位负责定位、人群、承诺、禁区；创作 Skill 负责长期表达、工作流和分段写法。
            两者同时注入，冲突时以定位/禁区为准。扩展 Skill 按任务模块路由，不覆盖当前 Skill。
          </Text>
        }
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card size="small">
            <Space direction="vertical" size={4}>
              <Text strong>语料来源一：样本库</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                去「素材 → 样本库」选中 3–20 篇有正文的外部笔记，用「更多操作 → 蒸馏成 Skill」。
              </Text>
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card size="small">
            <Space direction="vertical" size={4}>
              <Text strong>语料来源二：对标账号</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                去「素材 → 对标分析 → 相似账号」，找到目标账号后点「蒸馏写法」，产物会标注「模仿 XX」。
              </Text>
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {REFINE_ENTRIES.map((entry) => (
          <Col xs={24} md={12} key={entry.key}>
            <Card
              hoverable
              style={{ height: "100%" }}
              actions={[
                <Link to={entry.to} key="open">
                  进入{entry.title}
                </Link>,
              ]}
            >
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Space>
                  <span style={{ fontSize: 20 }}>{entry.icon}</span>
                  <Text strong>{entry.title}</Text>
                  <Tag>{entry.note}</Tag>
                </Space>
                <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
                  {entry.description}
                </Paragraph>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <NextStepBar
        description="写法定好后，下一步是选模板或直接生成草稿；两者可以同时用。"
        actions={[
          { label: "去创作 Skill", to: "/platforms/xhs/refine/skills", primary: true },
          { label: "去结构模板", to: "/platforms/xhs/refine/templates" },
        ]}
      />
    </div>
  );
}
