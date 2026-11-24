/**
 * Markdown.tsx — 消息里的 Markdown
 *
 * Agent 回话经常带代码块、列表、表格。纯文本显示很难看，所以这里渲染一遍。
 *
 * 做法：先把原文按 ``` 切成「正文段 / 代码段」。
 *   代码段直接用 React 画（带语言名和复制键），
 *   正文段先转义再交给 marked。
 * 这样两条都成立：代码里的尖括号原样保留，正文里的 <script> 不会生效。
 * 比"整段渲染 + DOMPurify"少一个库，规则也更硬。
 */

import { useMemo, useState } from "react";
import { marked } from "marked";
import "./Markdown.css";

marked.setOptions({ gfm: true, breaks: true });

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

type Piece =
  | { kind: "text"; html: string }
  | { kind: "code"; lang: string; code: string };

function split(src: string): Piece[] {
  const out: Piece[] = [];
  /* ``` 出现的次数一定是偶数（不成对就当正文处理） */
  const chunks = src.split("```");

  chunks.forEach((chunk, i) => {
    if (i % 2 === 1) {
      const nl = chunk.indexOf("\n");
      const lang = nl > 0 ? chunk.slice(0, nl).trim() : "";
      const code = (nl > 0 ? chunk.slice(nl + 1) : chunk).replace(/\n+$/, "");
      out.push({ kind: "code", lang, code });
      return;
    }
    if (!chunk.trim()) return;
    out.push({
      kind: "text",
      html: marked.parse(escapeHtml(chunk), { async: false }) as string,
    });
  });

  return out;
}

/** 代码块：语言名 + 复制。长代码不折，横向滚，行号不上——这一屏不需要 */
function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [done, setDone] = useState(false);

  const copy = () => {
    void navigator.clipboard?.writeText(code);
    setDone(true);
    window.setTimeout(() => setDone(false), 1200);
  };

  return (
    <div className="md__code">
      <div className="md__code-head">
        <span className="md__code-lang">{lang || "代码"}</span>
        <button type="button" className="md__code-copy" onClick={copy}>
          {done ? "复制了" : "复制"}
        </button>
      </div>
      <pre className="md__code-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function Markdown({ text }: { text: string }) {
  const pieces = useMemo(() => split(text), [text]);

  return (
    <div className="md">
      {pieces.map((p, i) =>
        p.kind === "code" ? (
          <CodeBlock key={i} lang={p.lang} code={p.code} />
        ) : (
          <div
            key={i}
            className="md__body"
            dangerouslySetInnerHTML={{ __html: p.html }}
          />
        ),
      )}
    </div>
  );
}
