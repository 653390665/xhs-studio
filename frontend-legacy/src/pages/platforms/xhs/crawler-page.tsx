import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloudDownloadOutlined,
  CommentOutlined,
  DatabaseOutlined,
  FileExcelOutlined,
  LinkOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Col, Empty, Form, Input, InputNumber, List, Progress, Row, Select, Space, Table, Tag, theme, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { crawlXhsDataStream, fetchAccounts, fetchSavedNotes, saveXhsNotesToLibrary } from "../../../lib/api";
import type { PlatformAccount, SavedNote, XhsDataCrawlItem, XhsDataCrawlMode, XhsSearchNote } from "../../../types";

const { Title, Text } = Typography;

const sortOptions = [
  { value: 0, label: "综合排序" },
  { value: 1, label: "最新" },
  { value: 2, label: "最多点赞" },
  { value: 3, label: "最多评论" },
  { value: 4, label: "最多收藏" },
];
const noteTypeOptions = [
  { value: 0, label: "不限类型" },
  { value: 1, label: "视频笔记" },
  { value: 2, label: "普通笔记" },
];
const noteTimeOptions = [
  { value: 0, label: "不限时间" },
  { value: 1, label: "一天内" },
  { value: 2, label: "一周内" },
  { value: 3, label: "半年内" },
];
const distanceOptions = [
  { value: 0, label: "不限距离" },
  { value: 1, label: "同城" },
  { value: 2, label: "附近" },
];

function splitUrls(value: string): string[] {
  return value.split(/\r?\n|,/).map((url) => url.trim()).filter(Boolean);
}

function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const noteExcelHeaders = [
  "笔记id", "笔记url", "笔记类型", "用户id", "用户主页url", "昵称", "头像url", "标题", "描述",
  "点赞数量", "收藏数量", "评论数量", "分享数量", "视频封面url", "视频地址url", "图片地址url列表",
  "标签", "上传时间", "ip归属地",
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}
function firstRecord(value: unknown): Record<string, unknown> {
  return Array.isArray(value) && value.length > 0 ? asRecord(value[0]) : {};
}
function textValue(...values: unknown[]): string {
  for (const value of values) {
    if (value !== undefined && value !== null && String(value).trim() !== "") return String(value);
  }
  return "";
}
function listValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item ?? "")).filter(Boolean).join("\n");
  return textValue(value);
}
function dateText(value: unknown): string {
  const numberValue = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numberValue) || numberValue <= 0) return textValue(value);
  const date = new Date(numberValue > 10_000_000_000 ? numberValue : numberValue * 1000);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}
function rawNoteItem(note: XhsDataCrawlItem["note"]): Record<string, unknown> {
  const raw = asRecord(note?.raw);
  const data = asRecord(raw.data);
  const firstItem = firstRecord(data.items);
  return Object.keys(firstItem).length > 0 ? firstItem : raw;
}
function rawNoteCard(note: XhsDataCrawlItem["note"]): Record<string, unknown> {
  const item = rawNoteItem(note);
  const noteCard = asRecord(item.note_card);
  const notePayload = asRecord(item.note);
  if (Object.keys(noteCard).length > 0) return noteCard;
  if (Object.keys(notePayload).length > 0) return notePayload;
  return item;
}
function noteTypeText(value: unknown): string {
  const text = textValue(value);
  if (text === "normal") return "图集";
  if (text === "video") return "视频";
  return text;
}

function spiderStyleNoteRow(item: XhsDataCrawlItem): string[] {
  const note = item.note;
  if (!note) return noteExcelHeaders.map(() => "");
  const rawItem = rawNoteItem(note);
  const card = rawNoteCard(note);
  const cardUser = asRecord(card.user);
  const cardAuthor = asRecord(card.author);
  const author = Object.keys(cardUser).length > 0 ? cardUser : cardAuthor;
  const cardInteract = asRecord(card.interact_info);
  const cardInteraction = asRecord(card.interaction);
  const interact = Object.keys(cardInteract).length > 0 ? cardInteract : cardInteraction;
  const video = asRecord(card.video);
  const videoMedia = asRecord(video.media);
  const stream = asRecord(videoMedia.stream);
  const h264 = firstRecord(stream.h264);
  const user_id = textValue(note.author_id, author.user_id, author.id);
  const note_url = textValue(note.note_url, card.note_url, card.url, rawItem.note_url, rawItem.url, item.source.startsWith("http") ? item.source : "");
  const upload_time = dateText(textValue(card.time, card.create_time, rawItem.time, rawItem.create_time));
  const originVideoKey = textValue(asRecord(video.consumer).origin_video_key);
  const video_addr = textValue(h264.master_url, h264.url, originVideoKey ? `https://sns-video-bd.xhscdn.com/${originVideoKey}` : "");
  return [
    textValue(note.note_id, card.note_id, card.id, rawItem.id), note_url,
    noteTypeText(textValue(note.type, card.type, rawItem.model_type)),
    user_id, user_id ? `https://www.xiaohongshu.com/user/profile/${user_id}` : "",
    textValue(note.author_name, author.nickname, author.name),
    textValue(note.author_avatar, author.avatar, author.avatar_url),
    textValue(note.title, card.title, card.display_title),
    textValue(note.content, card.desc, card.content),
    textValue(note.likes, interact.liked_count, interact.likes),
    textValue(note.collects, interact.collected_count, interact.collects),
    textValue(note.comments, interact.comment_count, interact.comments),
    textValue(note.shares, interact.share_count, interact.shares),
    textValue(note.cover_url, video.cover_url), video_addr,
    listValue(note.image_urls?.length ? note.image_urls : note.cover_url ? [note.cover_url] : []),
    listValue(note.tags), upload_time, textValue(card.ip_location, rawItem.ip_location),
  ];
}

function exportRowsToExcel(items: XhsDataCrawlItem[]) {
  const rows = items.map((item) => [item.status, item.source, item.error, ...spiderStyleNoteRow(item), item.comment_count, (item.comments ?? []).map((c) => c.content).join("\n")]);
  const headers = ["抓取状态", "来源", "错误", ...noteExcelHeaders, "抓取评论数", "评论内容"];
  const table = [headers, ...rows].map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("");
  const html = `<html><head><meta charset="UTF-8"></head><body><table>${table}</table></body></html>`;
  const blob = new Blob([html], { type: "application/vnd.ms-excel;charset=utf-8" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `xhs-crawl-${Date.now()}.xls`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export function XhsCrawlerPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [mode, setMode] = useState<XhsDataCrawlMode>("search");
  const [urls, setUrls] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pages, setPages] = useState(1);
  const [maxNotes, setMaxNotes] = useState(20);
  const [timeSleep, setTimeSleep] = useState(1.5);
  const [fetchCommentsChecked, setFetchCommentsChecked] = useState(false);
  const [filters, setFilters] = useState({ sort_type_choice: 0, note_type: 0, note_time: 0, note_range: 0, pos_distance: 0, geo: "" });
  const [items, setItems] = useState<XhsDataCrawlItem[]>([]);
  const [successCount, setSuccessCount] = useState(0);
  const [failedCount, setFailedCount] = useState(0);
  const [progressMsg, setProgressMsg] = useState<string | null>(null);
  /** Denominator announced by the server; 0 means "not known yet". */
  const [plannedTotal, setPlannedTotal] = useState(0);
  /** How many items the server has finished, from the SSE `processed` field. */
  const [processedCount, setProcessedCount] = useState(0);
  const [isLoadingAccounts, setIsLoadingAccounts] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [savedCount, setSavedCount] = useState(0);
  const [recentNotes, setRecentNotes] = useState<SavedNote[]>([]);
  const [error, setError] = useState<string | null>(null);

  const pcAccounts = useMemo(() => accounts.filter((a) => a.platform === "xhs" && a.sub_type === "pc"), [accounts]);

  async function loadAccounts() {
    setIsLoadingAccounts(true);
    setError(null);
    try {
      const loaded = await fetchAccounts("xhs");
      setAccounts(loaded);
      const first = loaded.find((a) => a.sub_type === "pc");
      setSelectedAccountId((c) => c ?? first?.id ?? null);
    } catch { setError("账号列表加载失败。"); }
    finally { setIsLoadingAccounts(false); }
  }

  async function handleRun(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    if (!selectedAccountId) { setError("请先选择一个 PC 账号。"); return; }
    const parsedUrls = splitUrls(urls);
    if (mode !== "search" && parsedUrls.length === 0) { setError("请至少输入一个笔记链接。"); return; }
    if (mode === "search" && !keyword.trim()) { setError("请填写搜索关键词。"); return; }
    setIsRunning(true);
    setItems([]);
    setSuccessCount(0);
    setFailedCount(0);
    setSavedCount(0);
    setProgressMsg("");
    setPlannedTotal(0);
    setProcessedCount(0);
    try {
      const summary = await crawlXhsDataStream(
        { account_id: selectedAccountId, mode, urls: parsedUrls, keyword: keyword.trim(), pages, max_notes: maxNotes, time_sleep: timeSleep, fetch_comments: mode === "comments" ? false : fetchCommentsChecked, ...filters, geo: filters.geo.trim() },
        (_index: number, item: unknown) => { setItems((prev) => [...prev, item as never]); },
        (msg: string) => { setProgressMsg(String(msg)); },
        (summary: unknown) => { void summary; },
        (planned: number) => { setPlannedTotal(planned); },
        (processed: number) => { setProcessedCount(processed); },
      );
      setSuccessCount(summary.success_count);
      setFailedCount(summary.failed_count);
      setProgressMsg("");
    } catch (err: unknown) {
      const axiosErr = err as { message?: string };
      setError(axiosErr?.message || "抓取失败");
    }
    finally { setIsRunning(false); }
  }

  useEffect(() => { void loadAccounts(); void loadRecentNotes(); }, []);

  async function loadRecentNotes() {
    try {
      const result = await fetchSavedNotes({ platform: "xhs", page_size: 6 });
      setRecentNotes(result.items);
    } catch {
      // Recent notes are a convenience panel; do not block the crawler form.
    }
  }

  const noPcAccount = !isLoadingAccounts && pcAccounts.length === 0;

  async function handleSaveToLibrary() {
    setError(null);
    if (!selectedAccountId) {
      setError("请先选择一个 PC 账号。");
      return;
    }
    const unique = new Map<string, XhsSearchNote>();
    for (const item of items) {
      const note = item.note;
      if (item.status !== "success" || !note?.note_id) continue;
      const url = note.note_url || (item.source.startsWith("http") ? item.source : "");
      unique.set(note.note_id, { ...note, note_url: url });
    }
    const notes = Array.from(unique.values());
    if (!notes.length) {
      setError("没有可保存的成功笔记。");
      return;
    }
    setIsSaving(true);
    try {
      const result = await saveXhsNotesToLibrary({ account_id: selectedAccountId, notes });
      setSavedCount(result.saved_count);
      message.success(`已保存 ${result.saved_count} 条笔记到样本库（重复笔记会自动更新）`);
      void loadRecentNotes();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "保存到样本库失败。");
    } finally {
      setIsSaving(false);
    }
  }

  const columns: ColumnsType<XhsDataCrawlItem> = [
    {
      title: "状态", dataIndex: "status", width: 80,
      render: (status: string) => status === "failed"
        ? <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>
        : <Tag icon={<CheckCircleOutlined />} color="success">成功</Tag>,
    },
    { title: "来源", dataIndex: "source", width: 200, ellipsis: true },
    { title: "标题", key: "title", width: 200, ellipsis: true, render: (_, item) => item.note?.title || "-" },
    { title: "作者", key: "author", width: 100, render: (_, item) => item.note?.author_name || "-" },
    { title: "互动", key: "engagement", width: 180, render: (_, item) => item.note ? <Text type="secondary" style={{ fontSize: 12 }}>赞{item.note.likes} 藏{item.note.collects} 评{item.note.comments}</Text> : "-" },
    { title: "评论", key: "comments", width: 80, render: (_, item) => <Space size={4}><CommentOutlined />{item.comment_count}</Space> },
    { title: "错误", dataIndex: "error", ellipsis: true, render: (err: string) => err ? <Text type="danger" style={{ fontSize: 12 }}>{err}</Text> : "-" },
  ];

  return (
    <div>
      {embedded ? (
        <Row justify="end" style={{ marginBottom: 16 }}>
          <Col>
            <Button icon={<ReloadOutlined />} onClick={loadAccounts} loading={isLoadingAccounts}>刷新账号</Button>
          </Col>
        </Row>
      ) : (
        <PageHeader
          eyebrow="批量采集"
          title="批量采集"
          description="按关键词或清单批量抓取外部样本，补全正文、图片和互动数据"
          action={
            <Button icon={<ReloadOutlined />} onClick={loadAccounts} loading={isLoadingAccounts}>
              刷新账号
            </Button>
          }
        />
      )}

      <Card style={{ marginBottom: 24 }}>
        <Form layout="vertical" onFinish={() => void handleRun()} style={{ marginBottom: 0 }}>
          <div style={{ marginBottom: 24 }}>
            <Text strong style={{ display: "block", marginBottom: 16 }}>抓取设置</Text>
            <Row gutter={[24, 0]}>
              <Col xs={24} md={8}>
                <Form.Item label="PC 账号" style={{ marginBottom: 20 }}>
                  <Select
                    value={selectedAccountId}
                    onChange={setSelectedAccountId}
                    placeholder="选择 PC 账号"
                    options={pcAccounts.map((a) => ({
                      value: a.id,
                      label: `${a.nickname || `PC 账号 ${a.id}`} · ${a.status}`,
                    }))}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="抓取方式" style={{ marginBottom: 20 }}>
                  <Select
                    value={mode}
                    onChange={(v) => setMode(v)}
                    options={[
                      { value: "search", label: "按关键词搜索（含正文）" },
                      { value: "note_urls", label: "按链接抓取（含正文）" },
                      { value: "comments", label: "只抓评论" },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  label="请求间隔（秒）"
                  style={{ marginBottom: 20 }}
                  tooltip="每篇之间等待的时间，带随机抖动。设 0 也会自动使用安全值，避免触发平台风控。"
                >
                  <InputNumber
                    min={0}
                    max={60}
                    step={0.5}
                    value={timeSleep}
                    onChange={(v) => setTimeSleep(v ?? 1.5)}
                    style={{ width: "100%" }}
                    addonAfter="秒"
                  />
                </Form.Item>
              </Col>
            </Row>
            <Checkbox
              checked={fetchCommentsChecked}
              onChange={(e) => setFetchCommentsChecked(e.target.checked)}
              disabled={mode === "comments"}
            >
              同时抓取评论（会显著增加请求量）
            </Checkbox>
          </div>

          <div style={{ paddingTop: 24, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
            {mode !== "search" ? (
              <Text strong style={{ display: "block", marginBottom: 16 }}>笔记链接</Text>
            ) : null}
            {mode === "search" ? (
              <>
                <Row gutter={[24, 0]}>
                  <Col xs={24} md={8}>
                    <Form.Item label="搜索关键词" style={{ marginBottom: 20 }}>
                      <Input
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                        placeholder="例如：AI 工具、一人公司"
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item
                      label="最多抓取篇数"
                      style={{ marginBottom: 20 }}
                      tooltip="每篇都要额外请求一次详情才有正文，篇数越多越慢。"
                    >
                      <InputNumber
                        min={1}
                        max={200}
                        value={maxNotes}
                        onChange={(v) => {
                          const n = v ?? 20;
                          setMaxNotes(n);
                          setPages(Math.max(1, Math.ceil(n / 20)));
                        }}
                        style={{ width: "100%" }}
                        addonAfter="篇"
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={8}>
                    <Form.Item label="排序" style={{ marginBottom: 20 }}>
                      <Select
                        value={filters.sort_type_choice}
                        onChange={(v) => setFilters((c) => ({ ...c, sort_type_choice: v }))}
                        options={sortOptions}
                      />
                    </Form.Item>
                  </Col>
                </Row>
                <Row gutter={[24, 0]}>
                  <Col xs={24} md={6}>
                    <Form.Item label="内容类型" style={{ marginBottom: 20 }}>
                      <Select
                        value={filters.note_type}
                        onChange={(v) => setFilters((c) => ({ ...c, note_type: v }))}
                        options={noteTypeOptions}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item label="发布时间" style={{ marginBottom: 20 }}>
                      <Select
                        value={filters.note_time}
                        onChange={(v) => setFilters((c) => ({ ...c, note_time: v }))}
                        options={noteTimeOptions}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item label="距离" style={{ marginBottom: 20 }}>
                      <Select
                        value={filters.pos_distance}
                        onChange={(v) => setFilters((c) => ({ ...c, pos_distance: v }))}
                        options={distanceOptions}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item
                      label="坐标"
                      style={{ marginBottom: 20 }}
                      tooltip="配合「距离」使用，填经纬度，例如 29.87,121.55。"
                    >
                      <Input
                        value={filters.geo}
                        onChange={(e) => setFilters((c) => ({ ...c, geo: e.target.value }))}
                        placeholder="29.87,121.55"
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </>
            ) : (
              <Form.Item
                label="笔记链接"
                style={{ marginBottom: 20 }}
                extra="每行一个链接，也可以用英文逗号分隔。"
              >
                <Input.TextArea
                  value={urls}
                  onChange={(e) => setUrls(e.target.value)}
                  placeholder="https://www.xiaohongshu.com/explore/..."
                  rows={4}
                />
              </Form.Item>
            )}
          </div>

          <Space>
            <Button type="primary" htmlType="submit" loading={isRunning} disabled={noPcAccount} icon={mode === "search" ? <SearchOutlined /> : <CloudDownloadOutlined />}>
              {isRunning ? "抓取中..." : "开始抓取"}
            </Button>
            <Button icon={<FileExcelOutlined />} onClick={() => items.length && exportRowsToExcel(items)} disabled={!items.length}>导出 Excel</Button>
            <Button
              icon={<DatabaseOutlined />}
              loading={isSaving}
              disabled={!items.length || isRunning || noPcAccount}
              onClick={() => void handleSaveToLibrary()}
            >
              保存到样本库
            </Button>
            {savedCount > 0 ? (
              <Button type="link" onClick={() => navigate("/platforms/xhs/assets/library")}>
                已入库 {savedCount} 条 · 去样本库
              </Button>
            ) : null}
          </Space>
        </Form>

        {error && <Alert message={error} type="error" showIcon style={{ marginTop: 16 }} />}
        {noPcAccount && (
          <Empty description="还没有可用的 PC 账号" style={{ marginTop: 24 }}>
            <Link to="/settings/accounts"><Button type="primary" icon={<LinkOutlined />}>去绑定账号</Button></Link>
          </Empty>
        )}
      </Card>

      <Card
        title={
          <Space size={12} wrap>
            <Title level={5} style={{ margin: 0 }}>抓取结果</Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              成功 {successCount} · 失败 {failedCount}
            </Text>
          </Space>
        }
      >
        {isRunning ? (
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <Text style={{ fontSize: 13 }}>
                {plannedTotal > 0
                  ? `正在抓取 ${processedCount} / ${plannedTotal} 篇`
                  : `正在抓取，已完成 ${processedCount} 篇`}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {progressMsg || "每篇都要额外请求详情，请耐心等待"}
              </Text>
            </div>
            <Progress
              percent={plannedTotal > 0 ? Math.min(99, Math.round((processedCount / plannedTotal) * 100)) : undefined}
              status="active"
              strokeColor={{ from: token.colorPrimary, to: token.colorSuccess }}
            />
          </div>
        ) : null}
        {items.length === 0 && !isRunning ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="执行抓取后，结果会显示在这里" />
        ) : (
          <Table<XhsDataCrawlItem>
            columns={columns}
            dataSource={items}
            rowKey={(_, index) => `${index}`}
            size="small"
            pagination={{ pageSize: 50 }}
            scroll={{ x: 900 }}
            rowClassName={(item) => item.status === "failed" ? "ant-table-row-error" : ""}
          />
        )}
      </Card>

      <Card
        title="最近入库"
        style={{ marginTop: 16 }}
        extra={<Link to="/platforms/xhs/assets/library">查看全部</Link>}
      >
        {recentNotes.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有入库笔记" />
        ) : (
          <List
            size="small"
            dataSource={recentNotes}
            renderItem={(note) => (
              <List.Item>
                <Link to={`/platforms/xhs/assets/library?q=${encodeURIComponent(note.note_id)}`}>
                  {note.title || note.note_id}
                </Link>
                <Space size={8}>
                  <Text type="secondary">{note.author_name || "-"}</Text>
                  <Tag>赞 {Number(note.likes || 0).toLocaleString()}</Tag>
                  <Tag>藏 {Number(note.collects || 0).toLocaleString()}</Tag>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>
    </div>
  );
}
