import { Button, Popover, Typography } from "antd";

import type { ViralTemplate } from "../../../../types";

const { Text, Paragraph } = Typography;

export function TemplatePreview({ template }: { template?: ViralTemplate }) {
  if (!template) return null;
  const payload = template.payload;
  const guide = (payload?.ai_guide || "").trim();
  const positional = payload?.kind === "positional";
  const formulas = positional
    ? (payload?.opening ?? []).map((item) => `${item.label}（${item.pct}%）`)
    : payload?.title_formulas ?? [];
  const structure = payload?.structure ?? [];

  const content = (
    <div style={{ maxWidth: 380, fontSize: 12, lineHeight: 1.7 }}>
      {guide ? (
        <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{guide}</Paragraph>
      ) : (
        <>
          {formulas.length > 0 && (
            <>
              <Text strong>{positional ? "开头写法" : "标题公式"}</Text>
              <ul style={{ paddingLeft: 16, margin: "4px 0 8px" }}>
                {formulas.slice(0, 4).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {structure.length > 0 && (
            <>
              <Text strong>正文结构</Text>
              <ol style={{ paddingLeft: 16, margin: "4px 0" }}>
                {structure.slice(0, 6).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            </>
          )}
        </>
      )}
    </div>
  );

  return (
    <div style={{ marginTop: 6, fontSize: 12 }}>
      <Text type="secondary">
        {guide
          ? "已 AI 精炼"
          : positional
            ? `位置结构 · ${structure.length} 步`
            : `标题公式 ${formulas.length} 条 · 结构 ${structure.length} 步`}
      </Text>
      <Popover content={content} title={template.name} trigger="click" placement="left">
        <Button type="link" size="small" style={{ padding: 0, marginLeft: 6 }}>
          查看会注入的规范
        </Button>
      </Popover>
    </div>
  );
}
