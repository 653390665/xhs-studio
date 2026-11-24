/**
 * ProjectDialog.tsx — 新建 / 编辑项目
 *
 * 为什么要弹窗而不是在左栏塞个输入框：
 *   项目不只是个名字。它得知道"这个项目做哪个方向"（一句话目标）和
 *   "它包含哪几个主题"——后者决定进项目后默认看哪几批笔记。
 *   一个输入框装不下这些，硬塞进左栏会把栏挤变形。
 *
 * 字段只留四个，且都能留空：
 *   名字必填，其余是"想写就写"，不拦人。新建项目的当下，用户往往
 *   还没想清楚要归哪些主题，逼他选只会让他关掉弹窗。
 */

import { useEffect, useMemo, useState } from "react";
import Button from "./Button";
import Modal from "./Modal";
import { loadTags } from "../lib/corpus";
import type { CorpusTag } from "../lib/corpus";
import type { Project } from "../lib/workspace";
import "./ProjectDialog.css";

const COLORS = ["#c6362c", "#3f6d8f", "#7a6a3a", "#4a6b4a", "#6b4a6b"];

export interface ProjectDraft {
  name: string;
  note?: string;
  color?: string;
  tag_ids?: number[];
}

export default function ProjectDialog({
  open,
  /** 传了就是编辑已有项目，不传是新建 */
  editing,
  onClose,
  onSubmit,
}: {
  open: boolean;
  editing?: Project | null;
  onClose: () => void;
  onSubmit: (draft: ProjectDraft) => void;
}) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [color, setColor] = useState(COLORS[0]);
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [tags, setTags] = useState<CorpusTag[]>([]);
  const [touched, setTouched] = useState(false);

  /* 每次打开都按当前编辑对象重置，避免上次输入串到这次 */
  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? "");
    setNote(editing?.note ?? "");
    setColor(editing?.color ?? COLORS[0]);
    setTagIds(editing?.tag_ids ?? []);
    setTouched(false);
    let alive = true;
    void loadTags().then((list) => {
      if (alive) setTags(list);
    });
    return () => {
      alive = false;
    };
  }, [open, editing]);

  const nameErr = touched && !name.trim() ? "还没写名字" : null;

  const toggleTag = (id: number) =>
    setTagIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );

  const submit = () => {
    setTouched(true);
    if (!name.trim()) return;
    onSubmit({
      name: name.trim(),
      note: note.trim() || undefined,
      color,
      tag_ids: tagIds,
    });
  };

  const count = useMemo(() => tagIds.length, [tagIds]);

  return (
    <Modal
      open={open}
      title={editing ? "改项目" : "新建项目"}
      hint={
        editing
          ? "改完立刻生效，已经记下的历史不会跟着变。"
          : "项目是个筐：你在素材页搜的、存的、提炼的，都会记到当前这个项目下面，之后能按日期翻回来。"
      }
      onClose={onClose}
      width={560}
      footNote={
        count > 0 ? `已选 ${count} 个主题` : "主题可以先不选，之后再补"
      }
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" size="sm" onClick={submit}>
            {editing ? "保存" : "建项目"}
          </Button>
        </>
      }
    >
      <div className="pd">
        <label className="pd__field">
          <span className="pd__k">
            项目名
            <span className="pd__req" aria-hidden="true">
              *
            </span>
          </span>
          <input
            className={`pd__input${nameErr ? " is-err" : ""}`}
            value={name}
            maxLength={24}
            placeholder="比如：向上管理专栏"
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setTouched(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />
          <span className="pd__foot">
            {nameErr ? (
              <span className="pd__err">{nameErr}</span>
            ) : (
              <span className="pd__hint">给自己看的名字，改得动</span>
            )}
            <span className="pd__count">{name.length}/24</span>
          </span>
        </label>

        <label className="pd__field">
          <span className="pd__k">
            一句话目标
            <span className="pd__opt">选填</span>
          </span>
          <input
            className="pd__input"
            value={note}
            maxLength={40}
            placeholder="比如：写一套让中层看得懂的向上沟通"
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />
          <span className="pd__foot">
            <span className="pd__hint">写下来，过两周还记得当初要做啥</span>
          </span>
        </label>

        <div className="pd__field">
          <span className="pd__k">
            这个项目用哪些主题
            <span className="pd__opt">选填</span>
          </span>
          {tags.length === 0 ? (
            <p className="pd__empty">
              还没有主题。现在只按项目归类，主题留作老数据的读法，可以先不选。
            </p>
          ) : (
            <div className="pd__tags">
              {tags.map((t) => {
                const on = tagIds.includes(t.id);
                return (
                  <button
                    key={t.id}
                    type="button"
                    className={`pd__tag${on ? " is-on" : ""}`}
                    aria-pressed={on}
                    onClick={() => toggleTag(t.id)}
                  >
                    <span
                      className="pd__tag-dot"
                      style={t.color ? { background: t.color } : undefined}
                      aria-hidden="true"
                    />
                    {t.name}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="pd__field">
          <span className="pd__k">标记颜色</span>
          <div className="pd__colors" role="radiogroup" aria-label="标记颜色">
            {COLORS.map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={c === color}
                aria-label={`颜色 ${c}`}
                className={`pd__color${c === color ? " is-on" : ""}`}
                style={{ background: c }}
                onClick={() => setColor(c)}
              />
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
