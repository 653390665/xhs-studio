import { Alert, Divider, Progress, Space, Tag, theme, Typography } from "antd";

import type { NoteDiagnosis } from "../../types";

const { Text } = Typography;

function formatNumber(value = 0): string {
  return Number(value).toLocaleString();
}

export function NoteDiagnosisPanel({ diagnosis }: { diagnosis: NoteDiagnosis }) {
  const { token } = theme.useToken();
  const levelColor =
    diagnosis.relative.level === "爆款"
      ? "red"
      : diagnosis.relative.level === "潜力"
        ? "orange"
        : diagnosis.relative.level === "正常"
          ? "green"
          : "default";
  const basisLabel =
    diagnosis.basis === "views" ? "观看口径" : diagnosis.basis === "fans" ? "粉丝口径（代理）" : "数据不足";
  return (
    <div style={{ marginTop: 8 }}>
      <Divider style={{ margin: "8px 0 12px" }}>内容诊断</Divider>
      <Space wrap style={{ marginBottom: 10 }}>
        <Tag color={levelColor}>{diagnosis.relative.level}</Tag>
        <Tag>{basisLabel}</Tag>
        <Tag>{diagnosis.data_quality.has_snapshots ? "有历史快照" : "首次快照"}</Tag>
        {diagnosis.relative.percentile !== null ? (
          <Tag>同账号 P{Math.round(diagnosis.relative.percentile)}</Tag>
        ) : null}
        <Text type="secondary" style={{ fontSize: 12 }}>
          基线 {formatNumber(diagnosis.relative.baseline_engagement)} · 相对{" "}
          {diagnosis.relative.multiple !== null ? `${diagnosis.relative.multiple}x` : "-"}
        </Text>
      </Space>
      <Alert
        type={diagnosis.proxy ? "warning" : "info"}
        showIcon
        style={{ marginBottom: 12 }}
        message={diagnosis.proxy ? "当前是代理口径" : "当前使用观看数据"}
        description={
          diagnosis.proxy
            ? "没有观看/曝光数据，暂用粉丝数或互动量做分母；补创作者后台数据后更准。"
            : undefined
        }
      />
      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        {diagnosis.funnel.stages.map((stage) => (
          <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ flex: "0 0 64px", fontSize: 12 }}>{stage.name}</span>
            {stage.percent !== null ? (
              <Progress
                percent={Math.min(100, Math.max(0, stage.percent))}
                size="small"
                showInfo={false}
                style={{ flex: 1, marginBottom: 0 }}
              />
            ) : (
              <div style={{ flex: 1, height: 6, background: token.colorFillSecondary, borderRadius: 8 }} />
            )}
            <span style={{ flex: "0 0 96px", fontSize: 12, textAlign: "right" }}>
              {stage.value !== null ? `${formatNumber(stage.value)}${stage.unit}` : "-"}
            </span>
            <Tag
              color={stage.status === "ok" ? "green" : stage.status === "proxy" ? "orange" : "default"}
              style={{ margin: 0 }}
            >
              {stage.status === "ok" ? "有数据" : stage.status === "proxy" ? "代理" : "缺数据"}
            </Tag>
          </div>
        ))}
      </Space>
      <Space wrap size={6} style={{ marginTop: 12 }}>
        {diagnosis.features.title_patterns.map((pattern) => (
          <Tag key={`pattern-${pattern}`}>{pattern}</Tag>
        ))}
        {diagnosis.features.cta_types.map((cta) => (
          <Tag key={`cta-${cta}`} color="blue">
            {cta}
          </Tag>
        ))}
        {diagnosis.features.tags.slice(0, 8).map((tag) => (
          <Tag key={`tag-${tag}`}>#{tag}</Tag>
        ))}
      </Space>
      <ul style={{ margin: "10px 0 0", paddingLeft: 18, color: token.colorTextSecondary, fontSize: 12 }}>
        {diagnosis.suggestions.map((suggestion) => (
          <li key={suggestion}>{suggestion}</li>
        ))}
      </ul>
      {diagnosis.funnel.missing.length ? (
        <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>
          缺失数据：{diagnosis.funnel.missing.join("、")}。补齐创作者后台的曝光/点击/完播/涨粉后，漏斗会更准。
        </Text>
      ) : null}
    </div>
  );
}
