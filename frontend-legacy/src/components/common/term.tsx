import { QuestionCircleOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";
import type { ReactNode } from "react";

import { GLOSSARY } from "../../app/glossary";

export function Term({
  k,
  children,
}: {
  k: keyof typeof GLOSSARY;
  children?: ReactNode;
}) {
  return (
    <Tooltip title={GLOSSARY[k]} styles={{ root: { maxWidth: 320 } }}>
      <span style={{ borderBottom: "1px dashed currentColor", cursor: "help" }}>
        {children ?? k}
        <QuestionCircleOutlined style={{ fontSize: 10, marginLeft: 3, opacity: 0.65 }} />
      </span>
    </Tooltip>
  );
}
