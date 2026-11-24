import {
  CheckOutlined,
  CommentOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  FireOutlined,
  HeartOutlined,
  LeftOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  PictureOutlined,
  ReloadOutlined,
  RightOutlined,
  SearchOutlined,
  StarOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Col, Descriptions, Drawer, Empty, Input, InputNumber, List, Modal, Row, Select, Space, Spin, Switch, Tag, theme, Typography } from "antd";
import { MouseEvent, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { fetchAccounts, fetchSavedNoteIds, fetchUserNotes, fetchXhsNoteComments, fetchXhsNoteDetail, fetchXhsProviderStatus, saveXhsNotesToLibrary, searchXhsNotes } from "../../../lib/api";
import { errorMessage } from "../../../lib/errors";
import type { NoteComment, PlatformAccount, XhsProviderStatus, XhsSearchEnrichment, XhsSearchNote, XhsSearchOptions } from "../../../types";

const { Title, Text, Paragraph } = Typography;

const sortOptions = [{ value: 0, label: "综合排序" }, { value: 1, label: "最新" }, { value: 2, label: "最多点赞" }, { value: 3, label: "最多评论" }, { value: 4, label: "最多收藏" }];
const noteTypeOptions = [{ value: 0, label: "不限类型" }, { value: 1, label: "视频笔记" }, { value: 2, label: "普通笔记" }];
const noteTimeOptions = [{ value: 0, label: "不限时间" }, { value: 1, label: "一天内" }, { value: 2, label: "一周内" }, { value: 3, label: "半年内" }];
const noteRangeOptions = [{ value: 0, label: "不限范围" }, { value: 1, label: "已看过" }, { value: 2, label: "未看过" }, { value: 3, label: "已关注" }];
const lowFanSortOptions = [
  { value: "like_fan_ratio", label: "赞粉比优先" },
  { value: "likes", label: "点赞优先" },
  { value: "engagement_rate", label: "互动率优先" },
  { value: "default", label: "小红书默认" },
];
type LowFanSort = "default" | "likes" | "like_fan_ratio" | "engagement_rate";
type LowFanFilter = {
  enabled: boolean;
  max_fans: number;
  min_likes: number;
  min_like_fan_ratio: number;
  max_profiles: number;
  sort_by: LowFanSort;
};

function formatMetric(value: number): string {
  if (value >= 10000) return `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}w`;
  return value.toLocaleString();
}
function formatNoteTime(note: XhsSearchNote): string {
  const ts = note.timestamp;
  if (ts) {
    const num = typeof ts === "number" ? ts : Number(ts);
    if (Number.isFinite(num) && num > 0) {
      return new Date(num > 1e12 ? num : num * 1000).toLocaleDateString("zh-CN");
    }
    if (typeof ts === "string") return ts;
  }
  const raw = note.raw ?? {};
  const data = (raw.data && typeof raw.data === "object") ? raw.data as Record<string, unknown> : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const item = (items[0] && typeof items[0] === "object") ? items[0] as Record<string, unknown> : {};
  const card = (item.note_card && typeof item.note_card === "object") ? item.note_card as Record<string, unknown> : {};
  const deep = card.time ?? card.create_time ?? card.last_update_time ?? raw.time ?? raw.create_time;
  if (deep) {
    const n = typeof deep === "number" ? deep : Number(deep);
    if (Number.isFinite(n) && n > 0) {
      return new Date(n > 1e12 ? n : n * 1000).toLocaleDateString("zh-CN");
    }
  }
  return "";
}
function rawString(note: XhsSearchNote, keys: string[]): string {
  for (const key of keys) { const v = note.raw?.[key]; if (typeof v === "string" && v) return v; } return "";
}
function getPreviewNoteUrl(note: XhsSearchNote): string {
  return note.note_url || rawString(note, ["note_url", "url", "share_url"]) || (note.note_id ? `https://www.xiaohongshu.com/explore/${note.note_id}` : "");
}
function getCoverUrl(note: XhsSearchNote): string { return note.cover_url || note.image_urls?.[0] || rawString(note, ["cover_url", "image_url"]); }
function getNoteImageUrls(note: XhsSearchNote): string[] { const urls = note.image_urls?.length ? note.image_urls : [getCoverUrl(note)]; return urls.filter((u): u is string => Boolean(u)); }
function getNoteVideoUrl(note: XhsSearchNote): string { return note.video_url || note.video_addr || rawString(note, ["video_url", "video_addr"]); }
function getNoteKindLabel(note: XhsSearchNote): "视频" | "图文" {
  const rawType = rawString(note, ["type", "note_type", "model_type"]);
  return `${note.type || rawType}`.toLowerCase().includes("video") || Boolean(getNoteVideoUrl(note)) ? "视频" : "图文";
}
function stopCardClick(e: MouseEvent<HTMLElement>) { e.stopPropagation(); }
function parseKeywords(value: string): string[] {
  const tokens = value
    .split(/[,，、;；\s]+/)
    .map((token) => token.trim())
    .filter(Boolean);
  return Array.from(new Set(tokens)).slice(0, 6);
}
function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
function downloadSearchCsv(notes: XhsSearchNote[], keyword: string) {
  const header = ["note_id", "title", "author_name", "author_id", "author_fans", "likes", "collects", "comments", "shares", "like_fan_ratio", "engagement_rate", "publish_time", "note_url"];
  const lines = notes.map((note) => [
    note.note_id,
    note.title,
    note.author_name,
    note.author_id,
    note.author_fans ?? "",
    note.likes,
    note.collects,
    note.comments,
    note.shares,
    note.like_fan_ratio ?? "",
    note.engagement_rate ?? "",
    formatNoteTime(note),
    getPreviewNoteUrl(note),
  ]);
  const csv = [header, ...lines].map((row) => row.map(csvCell).join(",")).join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `xhs-${keyword || "search"}-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export function XhsDiscoveryPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { token } = theme.useToken();
  const location = useLocation();
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);  const [providerStatus, setProviderStatus] = useState<XhsProviderStatus | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [authorNotes, setAuthorNotes] = useState<XhsSearchNote[]>([]);
  const [authorNotesOpen, setAuthorNotesOpen] = useState(false);
  const [authorNotesLoading, setAuthorNotesLoading] = useState(false);
  const [authorNotesName, setAuthorNotesName] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pendingKeyword, setPendingKeyword] = useState("");
  const [noteUrl, setNoteUrl] = useState("");
  const [filters, setFilters] = useState({ sort_type_choice: 0, note_type: 0, note_time: 0, note_range: 0, pos_distance: 0, geo: "" });
  const [lowFanFilter, setLowFanFilter] = useState<LowFanFilter>({
    enabled: false,
    max_fans: 10000,
    min_likes: 1000,
    min_like_fan_ratio: 0.5,
    max_profiles: 10,
    sort_by: "like_fan_ratio",
  });
  const [enrichment, setEnrichment] = useState<XhsSearchEnrichment | null>(null);
  const [rawTotal, setRawTotal] = useState(0);
  const [filteredOut, setFilteredOut] = useState(0);
  const [notes, setNotes] = useState<XhsSearchNote[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingAccounts, setIsLoadingAccounts] = useState(true);
  const [isSearching, setIsSearching] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isFetchingUrl, setIsFetchingUrl] = useState(false);
  const [isFetchingDetail, setIsFetchingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchedKeyword, setSearchedKeyword] = useState("");
  const [savingNoteIds, setSavingNoteIds] = useState<string[]>([]);
  const [savedNoteIds, setSavedNoteIds] = useState<string[]>([]);
  const [selectedNote, setSelectedNote] = useState<XhsSearchNote | null>(null);
  const [detailMediaIndex, setDetailMediaIndex] = useState(0);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [commentPreviewByNoteId, setCommentPreviewByNoteId] = useState<Record<string, NoteComment[]>>({});
  const [commentPreviewErrors, setCommentPreviewErrors] = useState<Record<string, string>>({});
  const [loadingCommentNoteIds, setLoadingCommentNoteIds] = useState<string[]>([]);

  const pcAccounts = useMemo(() => accounts.filter((a) => a.platform === "xhs" && a.sub_type === "pc"), [accounts]);
  const pcAccountOptions = useMemo(() => pcAccounts.map((a) => ({ value: a.id, label: `${a.nickname || `PC ${a.id}`} · ${a.status}` })), [pcAccounts]);

  // The RedFox provider authenticates with an API key and needs no XHS login, so a
  // PC account is optional there. While the status is unknown we keep the previous
  // behaviour and require an account.
  const isRedfox = providerStatus?.effective_provider === "redfox";
  const requiresAccount = !isRedfox;
  const requestAccountId = selectedAccountId ?? 0;

  async function loadProviderStatus() {
    try { setProviderStatus(await fetchXhsProviderStatus()); }
    catch { setProviderStatus(null); }
  }

  /** Returns false (and shows an error) when the current provider needs an account. */
  function ensureAccountReady(): boolean {
    if (!requiresAccount || selectedAccountId) return true;
    setError("请先选择一个 PC 账号。");
    return false;
  }

  async function loadAccounts() {
    setIsLoadingAccounts(true); setError(null);
    try { const loaded = await fetchAccounts("xhs"); setAccounts(loaded); const first = loaded.find((a) => a.sub_type === "pc"); setSelectedAccountId((c) => c ?? first?.id ?? null); }
    catch { setError("账号列表加载失败。"); } finally { setIsLoadingAccounts(false); }
  }

  function searchPayload(searchKeyword: string, nextPage: number, useLowFan = lowFanFilter.enabled): XhsSearchOptions | null {
    if (!ensureAccountReady()) return null;
    if (!searchKeyword.trim()) { setError("请输入要搜索的关键词。"); return null; }
    const payload: XhsSearchOptions = { account_id: requestAccountId, keyword: searchKeyword.trim(), page: nextPage, ...filters, geo: filters.geo.trim() };
    if (useLowFan) {
      payload.enrich_authors = true;
      payload.min_likes_for_profile = lowFanFilter.min_likes;
      payload.max_profiles = lowFanFilter.max_profiles;
      payload.max_fans = lowFanFilter.max_fans;
      payload.min_likes = lowFanFilter.min_likes;
      payload.min_like_fan_ratio = lowFanFilter.min_like_fan_ratio;
      payload.sort_by = lowFanFilter.sort_by;
    }
    return payload;
  }

  function sortNotes(items: XhsSearchNote[]): XhsSearchNote[] {
    if (!lowFanFilter.enabled || lowFanFilter.sort_by === "default") return items;
    const key: "likes" | "like_fan_ratio" | "engagement_rate" =
      lowFanFilter.sort_by === "likes"
        ? "likes"
        : lowFanFilter.sort_by === "engagement_rate"
          ? "engagement_rate"
          : "like_fan_ratio";
    return [...items].sort((a, b) => Number(b[key] ?? 0) - Number(a[key] ?? 0));
  }

  function mergeEnrichment(
    current: XhsSearchEnrichment | null | undefined,
    incoming: XhsSearchEnrichment | null | undefined,
  ): XhsSearchEnrichment | null {
    if (!current) return incoming ?? null;
    if (!incoming) return current;
    return {
      candidate_authors: current.candidate_authors + incoming.candidate_authors,
      profiles_requested: current.profiles_requested + incoming.profiles_requested,
      profiles_fetched: current.profiles_fetched + incoming.profiles_fetched,
      profile_errors: current.profile_errors + incoming.profile_errors,
      profiles_cached: Math.max(current.profiles_cached, incoming.profiles_cached),
    };
  }

  async function runSearch(
    nextPage: number,
    append: boolean,
    options?: { disableLowFan?: boolean; keyword?: string },
  ) {
    const keywords = parseKeywords(options?.keyword ?? keyword);
    if (!ensureAccountReady()) return;
    if (!keywords.length) { setError("请输入要搜索的关键词。"); return; }
    if (keywords.length > 6) { setError("一次最多搜索 6 个关键词，请减少后用逗号分隔。"); return; }
    const useLowFan = lowFanFilter.enabled && !options?.disableLowFan;
    setError(null);

    if (keywords.length > 1) {
      if (append) { setError("多关键词模式暂不支持翻页，请缩小关键词范围后单独搜索。"); return; }
      setIsSearching(true);
      try {
        const merged = new Map<string, XhsSearchNote>();
        let totalRaw = 0;
        let totalFilteredOut = 0;
        let aggregated: XhsSearchEnrichment | null = null;
        for (const singleKeyword of keywords) {
          const payload = searchPayload(singleKeyword, 1, useLowFan);
          if (!payload) throw new Error(requiresAccount ? "请先选择一个 PC 账号。" : "搜索参数无效。");
          if (payload.max_profiles) {
            payload.max_profiles = Math.max(1, Math.floor(payload.max_profiles / keywords.length));
          }
          const result = await searchXhsNotes(payload);
          totalRaw += result.raw_total ?? result.total;
          totalFilteredOut += result.filtered_out ?? 0;
          result.items.forEach((note) => merged.set(note.note_id, note));
          aggregated = mergeEnrichment(aggregated, result.enrichment);
        }
        setNotes(sortNotes(Array.from(merged.values())));
        setPage(1); setHasMore(false); setEnrichment(aggregated);
        setRawTotal(totalRaw); setFilteredOut(totalFilteredOut);
        setSearchedKeyword(keywords.join("、"));
        setCommentPreviewByNoteId({}); setCommentPreviewErrors({});
        void loadSavedNoteIds();
      } catch (err: unknown) {
        setError(errorMessage(err, "搜索失败，请检查网络和后端服务"));
      } finally { setIsSearching(false); }
      return;
    }

    const payload = searchPayload(keywords[0], nextPage, useLowFan);
    if (!payload) return;
    append ? setIsLoadingMore(true) : setIsSearching(true);
    try {
      const result = await searchXhsNotes(payload);
      setNotes((c) => sortNotes(append ? [...c, ...result.items] : result.items));
      setPage(result.page); setHasMore(result.has_more);
      setRawTotal(result.raw_total ?? result.total); setFilteredOut(result.filtered_out ?? 0);
      setEnrichment((current) => (!append || !current ? result.enrichment ?? null : mergeEnrichment(current, result.enrichment)));
      void loadSavedNoteIds();
      setCommentPreviewByNoteId((c) => append ? c : {}); setCommentPreviewErrors((c) => append ? c : {}); setSearchedKeyword(payload.keyword);
    } catch (err: unknown) { setError(errorMessage(err, "搜索失败，请检查网络和后端服务")); }
    finally { setIsSearching(false); setIsLoadingMore(false); }
  }

  async function handleLoadMore() { await runSearch(page + 1, true); }

  async function loadSavedNoteIds() {
    try {
      const ids = await fetchSavedNoteIds("xhs");
      setSavedNoteIds(ids.map((item: number) => String(item)));
    } catch { /* ignore */ }
  }

  async function handleSaveNote(note: XhsSearchNote) {
    setError(null); if (!selectedAccountId) { setError("保存到样本库需要一个 PC 账号，请先选择或绑定账号。"); return; }
    setSavingNoteIds((c) => [...c, note.note_id]);
    try { const d = await ensureNoteDetail(note); await saveXhsNotesToLibrary({ account_id: selectedAccountId, notes: [d] }); setSavedNoteIds((c) => c.includes(note.note_id) ? c : [...c, note.note_id]); }
    catch { setError("保存到样本库失败。"); } finally { setSavingNoteIds((c) => c.filter((id) => id !== note.note_id)); }
  }

  async function ensureNoteDetail(note: XhsSearchNote): Promise<XhsSearchNote> {
    const url = getPreviewNoteUrl(note);
    if (!url || (requiresAccount && !selectedAccountId)) return note;
    const detail = await fetchXhsNoteDetail({ account_id: requestAccountId, url });
    const merged = { ...note, ...detail, note_url: detail.note_url || url };
    setNotes((c) => c.map((n) => (n.note_id === note.note_id ? (merged as XhsSearchNote) : n)));
    setSelectedNote((c) => (c?.note_id === note.note_id ? (merged as XhsSearchNote) : c)); return merged;
  }

  async function handleFetchUrlDetail() {
    setError(null); if (!ensureAccountReady()) return;
    const cleanUrl = noteUrl.trim(); if (!cleanUrl) { setError("请输入小红书笔记 URL。"); return; }
    setIsFetchingUrl(true);
    try {
      const detail = await fetchXhsNoteDetail({ account_id: requestAccountId, url: cleanUrl });
      const merged = { ...detail, note_url: detail.note_url || cleanUrl };
      setNotes([merged as XhsSearchNote]); setDetailMediaIndex(0); setSelectedNote(merged as XhsSearchNote); setHasMore(false); setPage(1);
      setSearchedKeyword("URL 直查"); setSavedNoteIds([]); setCommentPreviewByNoteId({}); setCommentPreviewErrors({});
    } catch (err: unknown) { setError(errorMessage(err, "URL 直查失败，请检查网络")); } finally { setIsFetchingUrl(false); }
  }

  async function openDetail(note: XhsSearchNote) {
    setDetailMediaIndex(0); setSelectedNote(note); setDetailError(null);
    if (requiresAccount && !selectedAccountId) { setDetailError("请先选择一个 PC 账号。"); return; }
    const url = getPreviewNoteUrl(note); if (!url) { setDetailError("缺少可用于获取详情的笔记 URL。"); return; }
    setIsFetchingDetail(true);
    try { const detail = await fetchXhsNoteDetail({ account_id: requestAccountId, url }); setDetailMediaIndex(0); setSelectedNote({ ...note, ...detail, note_url: detail.note_url || url }); }
    catch { setDetailError("详情加载失败，已保留搜索结果预览。"); } finally { setIsFetchingDetail(false); }
  }

  function closeDetail() { setSelectedNote(null); setDetailMediaIndex(0); setDetailError(null); }

  function getChildComments(noteId: string, parentId: string): NoteComment[] {
    return (commentPreviewByNoteId[noteId] ?? []).filter((c) => c.parent_comment_id === parentId);
  }

  async function handlePreviewComments(note: XhsSearchNote) {
    setError(null); if (!ensureAccountReady()) return;
    const url = getPreviewNoteUrl(note);
    if (!url) { setCommentPreviewErrors((c) => ({ ...c, [note.note_id]: "缺少笔记 URL。" })); return; }
    if (isRedfox) { setCommentPreviewErrors((c) => ({ ...c, [note.note_id]: "RedFox 的评论接口是异步任务（约 24 小时后才可见），暂不支持即时预览；请在 PC 数据源下查看评论。" })); return; }
    if (commentPreviewByNoteId[note.note_id]) { setCommentPreviewByNoteId((c) => { const n = { ...c }; delete n[note.note_id]; return n; }); return; }
    setLoadingCommentNoteIds((c) => [...c, note.note_id]); setCommentPreviewErrors((c) => ({ ...c, [note.note_id]: "" }));
    try { const r = await fetchXhsNoteComments({ account_id: requestAccountId, note_url: url }); setCommentPreviewByNoteId((c) => ({ ...c, [note.note_id]: r.items })); }
    catch { setCommentPreviewErrors((c) => ({ ...c, [note.note_id]: "评论加载失败。" })); }
    finally { setLoadingCommentNoteIds((c) => c.filter((id) => id !== note.note_id)); }
  }

  useEffect(() => { void loadAccounts(); void loadSavedNoteIds(); void loadProviderStatus(); }, []);

  // 从爆款模板/关键词组/榜单跳转过来时自动带关键词搜索
  useEffect(() => {
    const incoming = (new URLSearchParams(location.search).get("keyword") || "").trim();
    if (incoming) {
      setKeyword(incoming);
      setPendingKeyword(incoming);
    }
  }, [location.search]);

  useEffect(() => {
    if (!pendingKeyword || isLoadingAccounts) return;
    if (requiresAccount && !selectedAccountId) return;
    setPendingKeyword("");
    void runSearch(1, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingKeyword, isLoadingAccounts, selectedAccountId]);

  const noPcAccount = !isLoadingAccounts && pcAccounts.length === 0;
  const selImgUrls = selectedNote ? getNoteImageUrls(selectedNote) : [];
  const selVideoUrl = selectedNote ? getNoteVideoUrl(selectedNote) : "";
  const selMediaIdx = selImgUrls.length ? Math.min(detailMediaIndex, selImgUrls.length - 1) : 0;

  async function openAuthorNotes() {
    const note = selectedNote;
    if (!note?.author_id) return;
    setAuthorNotesName(note.author_name || "该账号");
    setAuthorNotesOpen(true);
    setAuthorNotesLoading(true);
    setAuthorNotes([]);
    try {
      const data = await fetchUserNotes({ account_id: requestAccountId, user_id: note.author_id, limit: 20 });
      setAuthorNotes(data.items ?? []);
    } catch {
      setError("读取作者作品失败，请确认账号登录态有效。");
    } finally {
      setAuthorNotesLoading(false);
    }
  }

  function isLowFanViral(note: XhsSearchNote): boolean {    const fans = note.author_fans ?? 0;
    return fans > 0
      && fans <= lowFanFilter.max_fans
      && (note.likes ?? 0) >= lowFanFilter.min_likes
      && (note.like_fan_ratio ?? 0) >= lowFanFilter.min_like_fan_ratio;
  }

  return (
    <div>
      {embedded ? (
        <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
          <Col>
            <Space align="center" wrap>
              <Tag color={isRedfox ? "purple" : "default"} style={{ marginInlineEnd: 0 }}>
                数据源：{isRedfox ? "RedFox 接口" : "PC 登录态"}
              </Tag>
              {isRedfox ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  RedFox 无需登录小红书账号即可搜索
                  {providerStatus?.redfox_daily_call_limit ? `；今日已用 ${providerStatus.redfox_usage?.count ?? 0}/${providerStatus.redfox_daily_call_limit} 次` : ""}
                  ；评论为异步任务，请切回 PC 数据源查看评论。
                </Text>
              ) : null}
            </Space>
          </Col>
          <Col><Button icon={<ReloadOutlined />} onClick={() => { void loadAccounts(); void loadProviderStatus(); }} loading={isLoadingAccounts}>刷新账号</Button></Col>
        </Row>
      ) : (
        <PageHeader
          eyebrow="搜索样本"
          title="搜索样本"
          description={`按关键词或链接找外部笔记，查看详情、评论和原文，保存到样本库。${isRedfox ? "RedFox 无需登录小红书账号；评论为异步任务，请切回 PC 数据源查看。" : ""}${isRedfox && providerStatus?.redfox_daily_call_limit ? ` 今日已用 ${providerStatus.redfox_usage?.count ?? 0}/${providerStatus.redfox_daily_call_limit} 次。` : ""}`}
          action={
            <Space>
              <Tag color={isRedfox ? "purple" : "default"} style={{ marginInlineEnd: 0 }}>
                数据源：{isRedfox ? "RedFox 接口" : "PC 登录态"}
              </Tag>
              <Button icon={<ReloadOutlined />} onClick={() => { void loadAccounts(); void loadProviderStatus(); }} loading={isLoadingAccounts}>
                刷新账号
              </Button>
            </Space>
          }
        />
      )}

      <Card style={{ marginBottom: 24 }}>
        <form onSubmit={(e) => { e.preventDefault(); void runSearch(1, false); }}>
          <Row gutter={[12, 12]}>
            <Col span={6}><div style={{ marginBottom: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>搜索账号{isRedfox ? "（可选）" : ""}</Text></div><Select value={selectedAccountId} onChange={setSelectedAccountId} allowClear={isRedfox} placeholder={isRedfox ? "RedFox 无需账号，可留空" : "选择 PC 账号"} style={{ width: "100%" }} options={pcAccountOptions} /></Col>
            <Col span={6}><div style={{ marginBottom: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>关键词</Text></div><Input.Search value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="低卡早餐、通勤穿搭；多个关键词用逗号分隔" loading={isSearching} onSearch={() => void runSearch(1, false)} enterButton /></Col>
            <Col span={3}><div style={{ marginBottom: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>排序</Text></div><Select value={filters.sort_type_choice} onChange={(v) => setFilters((c) => ({ ...c, sort_type_choice: v }))} style={{ width: "100%" }} options={sortOptions} /></Col>
            <Col span={3}><div style={{ marginBottom: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>类型</Text></div><Select value={filters.note_type} onChange={(v) => setFilters((c) => ({ ...c, note_type: v }))} style={{ width: "100%" }} options={noteTypeOptions} /></Col>
            <Col span={3}><div style={{ marginBottom: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>时间</Text></div><Select value={filters.note_time} onChange={(v) => setFilters((c) => ({ ...c, note_time: v }))} style={{ width: "100%" }} options={noteTimeOptions} /></Col>
            <Col span={3}><div style={{ marginBottom: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>范围</Text></div><Select value={filters.note_range} onChange={(v) => setFilters((c) => ({ ...c, note_range: v }))} style={{ width: "100%" }} options={noteRangeOptions} /></Col>
          </Row>
          <Row gutter={[12, 12]} align="middle" style={{ marginTop: 12, padding: "10px 12px", background: token.colorFillQuaternary, borderRadius: 8 }}>
            <Col>
              <Space>
                <Switch size="small" checked={lowFanFilter.enabled} onChange={(v) => setLowFanFilter((c) => ({ ...c, enabled: v }))} />
                <Text strong style={{ fontSize: 13 }}><FireOutlined style={{ color: token.colorWarning }} /> 低粉高赞筛选</Text>
              </Space>
            </Col>
            {lowFanFilter.enabled && (
              <>
                <Col span={3}><Text type="secondary" style={{ fontSize: 12 }}>粉丝上限</Text><InputNumber min={100} step={1000} value={lowFanFilter.max_fans} onChange={(v) => setLowFanFilter((c) => ({ ...c, max_fans: Number(v ?? 0) }))} style={{ width: "100%" }} /></Col>
                <Col span={3}><Text type="secondary" style={{ fontSize: 12 }}>点赞下限</Text><InputNumber min={0} step={100} value={lowFanFilter.min_likes} onChange={(v) => setLowFanFilter((c) => ({ ...c, min_likes: Number(v ?? 0) }))} style={{ width: "100%" }} /></Col>
                <Col span={3}><Text type="secondary" style={{ fontSize: 12 }}>赞粉比下限</Text><InputNumber min={0} step={0.1} precision={2} value={lowFanFilter.min_like_fan_ratio} onChange={(v) => setLowFanFilter((c) => ({ ...c, min_like_fan_ratio: Number(v ?? 0) }))} style={{ width: "100%" }} /></Col>
                <Col span={3}><Text type="secondary" style={{ fontSize: 12 }}>最多查作者数</Text><InputNumber min={1} max={20} value={lowFanFilter.max_profiles} onChange={(v) => setLowFanFilter((c) => ({ ...c, max_profiles: Number(v ?? 10) }))} style={{ width: "100%" }} /></Col>
                <Col span={4}><Text type="secondary" style={{ fontSize: 12 }}>结果排序</Text><Select value={lowFanFilter.sort_by} onChange={(v: LowFanSort) => setLowFanFilter((c) => ({ ...c, sort_by: v }))} style={{ width: "100%" }} options={lowFanSortOptions} /></Col>
              </>
            )}
          </Row>
          {lowFanFilter.enabled && (
            <Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
              仅对点赞 ≥ {lowFanFilter.min_likes} 的笔记补查作者粉丝，单页最多查 {lowFanFilter.max_profiles} 位作者；点赞低于下限或未取到粉丝数的笔记会被过滤掉。翻页后会继续补查。多个关键词时会自动分摊作者查询额度。
            </Text>
          )}
          <Row gutter={12} style={{ marginTop: 12 }} align="bottom">
            <Col span={6}><div style={{ marginBottom: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>笔记 URL</Text></div><Input value={noteUrl} onChange={(e) => setNoteUrl(e.target.value)} placeholder="https://www.xiaohongshu.com/explore/..." /></Col>
            <Col><Button icon={<SearchOutlined />} loading={isFetchingUrl} disabled={requiresAccount && noPcAccount} onClick={handleFetchUrlDetail}>URL 直查</Button></Col>
          </Row>
        </form>
        {error && <Alert message={error} type="error" showIcon style={{ marginTop: 12 }} closable onClose={() => setError(null)} />}
        {requiresAccount && noPcAccount && <Empty description="还没有可用的 PC 账号" style={{ marginTop: 24 }}><Link to="/settings/accounts"><Button type="primary" icon={<LinkOutlined />}>去绑定账号</Button></Link></Empty>}
      </Card>

      <Card title={
        <Row justify="space-between" align="middle" style={{ width: "100%" }}>
          <Col>
            <Space wrap>
              <Title level={5} style={{ margin: 0 }}>{searchedKeyword ? `"${searchedKeyword}" 的搜索结果` : "搜索结果"}</Title>
              <Tag>{notes.length} 篇</Tag>
              {rawTotal > 0 && <Text type="secondary" style={{ fontSize: 12 }}>原始 {rawTotal} 篇{filteredOut > 0 ? `，筛选掉 ${filteredOut} 篇` : ""}</Text>}
              {enrichment && <Text type="secondary" style={{ fontSize: 12 }}>已补查作者 {enrichment.profiles_fetched}/{enrichment.candidate_authors} 位{enrichment.profile_errors ? `，失败 ${enrichment.profile_errors} 位` : ""}</Text>}
            </Space>
          </Col>
          <Col>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadSearchCsv(notes, searchedKeyword)} disabled={!notes.length}>导出本页 CSV</Button>
          </Col>
        </Row>
      }>
        {notes.length === 0 ? (
          filteredOut > 0 && lowFanFilter.enabled ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={`搜索返回 ${rawTotal} 篇，但低粉高赞筛选过滤掉了 ${filteredOut} 篇；点赞低于 ${lowFanFilter.min_likes} 或未补查到粉丝的作者都会被过滤。`}
            >
              <Space>
                <Button
                  type="primary"
                  onClick={() => {
                    setLowFanFilter((current) => ({ ...current, enabled: false }));
                    void runSearch(1, false, { disableLowFan: true });
                  }}
                >
                  关闭低粉高赞筛选重新搜索
                </Button>
                <Button onClick={() => setKeyword(parseKeywords(keyword)[0] ?? "")}>只搜第一个关键词</Button>
              </Space>
            </Empty>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                searchedKeyword
                  ? "这次搜索没有返回笔记。"
                  : "输入关键词后，搜索结果会以笔记卡片显示在这里。"
              }
            >
              {!searchedKeyword ? (
                <Space wrap>
                  {["Excel 技巧", "AI 工具", "副业"].map((term) => (
                    <Button
                      key={term}
                      size="small"
                      onClick={() => {
                        setKeyword(term);
                        void runSearch(1, false, { keyword: term });
                      }}
                    >
                      试搜「{term}」
                    </Button>
                  ))}
                </Space>
              ) : null}
            </Empty>
          )
        ) : (
          <>
            <Row gutter={[16, 16]}>
              {notes.map((note) => {
                const coverUrl = getCoverUrl(note);
                const originalUrl = getPreviewNoteUrl(note);
                const kind = getNoteKindLabel(note);
                return (
                  <Col xs={12} sm={8} md={6} lg={4} xl={4} key={`${note.note_id}-${note.title}`}>
                    <Card hoverable size="small" style={{ overflow: "hidden" }} onClick={() => void openDetail(note)}
                      cover={
                        <div style={{ position: "relative", background: token.colorFillQuaternary }}>
                          {coverUrl
                            ? <img src={coverUrl} alt={note.title || "封面"} referrerPolicy="no-referrer" style={{ width: "100%", aspectRatio: "1/1", objectFit: "cover", display: "block" }} />
                            : <div style={{ width: "100%", aspectRatio: "1/1", display: "flex", alignItems: "center", justifyContent: "center", color: token.colorTextQuaternary, fontSize: 28 }}><PictureOutlined /></div>}
                          <Tag color={kind === "视频" ? "purple" : "blue"} style={{ position: "absolute", top: 8, left: 8 }} icon={kind === "视频" ? <PlayCircleOutlined /> : <PictureOutlined />}>{kind}</Tag>
                          {isLowFanViral(note) && <Tag color="gold" style={{ position: "absolute", top: 8, right: 8 }} icon={<FireOutlined />}>低粉爆款</Tag>}
                        </div>
                      }>
                      <Card.Meta title={<Text ellipsis style={{ fontSize: 13 }}>{note.title || "未命名笔记"}</Text>} description={<><Text type="secondary" style={{ fontSize: 12 }}>{note.author_name || "未知作者"}</Text>{formatNoteTime(note) && <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>{formatNoteTime(note)}</Text>}</>} />
                      <Space size={12} style={{ marginTop: 8, fontSize: 12, color: token.colorTextTertiary }}>
                        <span><HeartOutlined /> {formatMetric(note.likes)}</span>
                        <span><StarOutlined /> {formatMetric(note.collects)}</span>
                        <span><CommentOutlined /> {formatMetric(note.comments)}</span>
                      </Space>
                      {(note.author_fans !== undefined || note.like_fan_ratio !== undefined) && (
                        <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>粉丝 {note.author_fans ? formatMetric(note.author_fans) : "—"}</Text>
                          <Tag color={isLowFanViral(note) ? "gold" : "default"} style={{ marginInlineEnd: 0, fontSize: 11 }}>
                            赞粉比 {(note.like_fan_ratio ?? 0).toFixed(2)}
                          </Tag>
                        </div>
                      )}
                      <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }} onClick={stopCardClick}>
                        <Button size="small" type={savedNoteIds.includes(note.note_id) ? "default" : "primary"} ghost={!savedNoteIds.includes(note.note_id)} icon={savedNoteIds.includes(note.note_id) ? <CheckOutlined /> : <DatabaseOutlined />} loading={savingNoteIds.includes(note.note_id)} disabled={savedNoteIds.includes(note.note_id) || !selectedAccountId} title={selectedAccountId ? undefined : "保存到样本库需要先选择一个 PC 账号"} onClick={() => void handleSaveNote(note)}>
                          {savedNoteIds.includes(note.note_id) ? "已保存" : "保存"}
                        </Button>
                        <Button size="small" icon={<CommentOutlined />} loading={loadingCommentNoteIds.includes(note.note_id)} onClick={() => void handlePreviewComments(note)}>
                          {commentPreviewByNoteId[note.note_id] ? "收起" : "评论"}
                        </Button>
                        {originalUrl && <Button size="small" icon={<LinkOutlined />} href={originalUrl} target="_blank" rel="noreferrer" onClick={stopCardClick}>原文</Button>}
                      </div>
                      {commentPreviewErrors[note.note_id] && <Alert message={commentPreviewErrors[note.note_id]} type="error" style={{ marginTop: 8, fontSize: 12 }} showIcon />}
                      {commentPreviewByNoteId[note.note_id] && (
                        <div style={{ marginTop: 8, borderTop: `1px solid ${token.colorBorderSecondary}`, paddingTop: 8 }} onClick={stopCardClick}>
                          {commentPreviewByNoteId[note.note_id].length === 0 ? <Text type="secondary" style={{ fontSize: 12 }}>暂无评论</Text> : null}
                          {commentPreviewByNoteId[note.note_id].filter((c) => !c.parent_comment_id).slice(0, 4).map((c) => (
                            <div key={c.comment_id} style={{ marginBottom: 6, fontSize: 12 }}>
                              <Text strong style={{ fontSize: 12 }}>{c.user_name}</Text> <Text type="secondary" style={{ fontSize: 11 }}>{c.created_at_remote} · {c.like_count} likes</Text>
                              <div style={{ color: token.colorTextSecondary }}>{c.content}</div>
                              {getChildComments(note.note_id, c.comment_id).map((r) => (
                                <div key={r.comment_id} style={{ marginLeft: 16, marginTop: 4 }}>
                                  <Text strong style={{ fontSize: 11 }}>{r.user_name}</Text> <Text type="secondary" style={{ fontSize: 11 }}>{r.like_count} likes</Text>
                                  <div style={{ color: token.colorTextTertiary, fontSize: 12 }}>{r.content}</div>
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      )}
                    </Card>
                  </Col>
                );
              })}
            </Row>
            <div style={{ textAlign: "center", marginTop: 24 }}>
              <Button onClick={handleLoadMore} disabled={!hasMore || isLoadingMore} loading={isLoadingMore}>{hasMore ? "加载更多" : "没有更多了"}</Button>
            </div>
          </>
        )}
      </Card>

      <Drawer title={selectedNote?.title || "笔记详情"} open={!!selectedNote} onClose={closeDetail} width={640} styles={{ body: { background: token.colorBgElevated } }}>
        {selectedNote && (
          <div>
            {isFetchingDetail && <Spin style={{ display: "block", textAlign: "center", margin: "16px 0" }} />}
            {detailError && <Alert message={detailError} type="warning" showIcon style={{ marginBottom: 12 }} />}
            {selVideoUrl && getNoteKindLabel(selectedNote) === "视频" ? (
              <div style={{ marginBottom: 16 }}>
                <div style={{ position: "relative", background: token.colorFillQuaternary, borderRadius: 8, overflow: "hidden" }}>
                  {selImgUrls.length ? <img src={selImgUrls[0]} alt="视频封面" referrerPolicy="no-referrer" style={{ width: "100%", maxHeight: 400, objectFit: "contain", display: "block" }} /> : <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center" }}><PlayCircleOutlined style={{ fontSize: 40, color: token.colorTextQuaternary }} /></div>}
                  <Tag color="purple" style={{ position: "absolute", top: 8, left: 8 }}><PlayCircleOutlined /> 视频封面</Tag>
                </div>
                <Button type="primary" icon={<LinkOutlined />} href={selVideoUrl} target="_blank" rel="noreferrer" style={{ marginTop: 8 }} block>打开视频</Button>
              </div>
            ) : selImgUrls.length ? (
              <div style={{ marginBottom: 16 }}>
                <div style={{ position: "relative", background: token.colorFillQuaternary, borderRadius: 8, overflow: "hidden", textAlign: "center" }}>
                  <img src={selImgUrls[selMediaIdx]} alt="笔记图片" referrerPolicy="no-referrer" style={{ maxWidth: "100%", maxHeight: 400, objectFit: "contain" }} />
                  {selImgUrls.length > 1 && (
                    <>
                      <Button shape="circle" icon={<LeftOutlined />} size="small" style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)" }} onClick={() => setDetailMediaIndex((c) => (c - 1 + selImgUrls.length) % selImgUrls.length)} />
                      <Button shape="circle" icon={<RightOutlined />} size="small" style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)" }} onClick={() => setDetailMediaIndex((c) => (c + 1) % selImgUrls.length)} />
                      <Tag style={{ position: "absolute", bottom: 8, right: 8 }}>{selMediaIdx + 1}/{selImgUrls.length}</Tag>
                    </>
                  )}
                </div>
                {selImgUrls.length > 1 && (
                  <Space size={4} style={{ marginTop: 8, overflowX: "auto" }}>
                    {selImgUrls.map((url, i) => (
                      <div key={url} onClick={() => setDetailMediaIndex(i)} style={{ width: 48, height: 48, borderRadius: 8, overflow: "hidden", cursor: "pointer", border: i === selMediaIdx ? `2px solid ${token.colorPrimary}` : "2px solid transparent", flexShrink: 0 }}>
                        <img src={url} alt="" referrerPolicy="no-referrer" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      </div>
                    ))}
                  </Space>
                )}
              </div>
            ) : null}

            <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="作者">{selectedNote.author_id ? <Typography.Link href={`https://www.xiaohongshu.com/user/profile/${selectedNote.author_id}`} target="_blank" rel="noreferrer">{selectedNote.author_name || "-"}</Typography.Link> : (selectedNote.author_name || "-")}
                {selectedNote.author_id ? (
                  <Button type="link" size="small" loading={authorNotesLoading} onClick={() => void openAuthorNotes()} style={{ paddingLeft: 8 }}>
                    看 TA 的全部作品
                  </Button>
                ) : null}
              </Descriptions.Item>
              <Descriptions.Item label="作者粉丝">{selectedNote.author_fans ? formatMetric(selectedNote.author_fans) : "未获取"}</Descriptions.Item>
              <Descriptions.Item label="赞粉比">{selectedNote.like_fan_ratio !== undefined ? selectedNote.like_fan_ratio.toFixed(2) : "—"}</Descriptions.Item>
              <Descriptions.Item label="互动率">{selectedNote.engagement_rate !== undefined ? `${(selectedNote.engagement_rate * 100).toFixed(1)}%` : "—"}</Descriptions.Item>
              <Descriptions.Item label="互动">赞 {formatMetric(selectedNote.likes)} · 藏 {formatMetric(selectedNote.collects)} · 评 {formatMetric(selectedNote.comments)}</Descriptions.Item>
              <Descriptions.Item label="笔记 ID">{selectedNote.note_id || "-"}</Descriptions.Item>
              {formatNoteTime(selectedNote) && <Descriptions.Item label="发布时间">{formatNoteTime(selectedNote)}</Descriptions.Item>}
              <Descriptions.Item label="作品链接"><Typography.Link href={getPreviewNoteUrl(selectedNote)} target="_blank" rel="noreferrer" style={{ fontSize: 12, wordBreak: "break-all" }}>{getPreviewNoteUrl(selectedNote) || "-"}</Typography.Link></Descriptions.Item>
            </Descriptions>

            <Modal
              open={authorNotesOpen}
              onCancel={() => setAuthorNotesOpen(false)}
              footer={null}
              width={760}
              title={`${authorNotesName} 的作品`}
            >
              {authorNotesLoading ? (
                <div style={{ padding: 48, textAlign: "center" }}><Spin /></div>
              ) : authorNotes.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有读取到该账号的作品" />
              ) : (
                <List
                  dataSource={authorNotes}
                  style={{ maxHeight: 520, overflowY: "auto" }}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button key="open" size="small" onClick={() => window.open(getPreviewNoteUrl(item), "_blank", "noopener")}>
                          打开
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        avatar={
                          item.cover_url ? (
                            <img
                              src={item.cover_url}
                              alt=""
                              referrerPolicy="no-referrer"
                              style={{ width: 48, height: 64, objectFit: "cover", borderRadius: 8 }}
                            />
                          ) : (
                            <div style={{ width: 48, height: 64, borderRadius: 8, background: token.colorFillQuaternary }} />
                          )
                        }
                        title={<span style={{ fontSize: 13 }}>{item.title || "(无标题)"}</span>}
                        description={
                          <span style={{ fontSize: 12 }}>
                            赞 {formatMetric(item.likes)} · 藏 {formatMetric(item.collects)} · 评 {formatMetric(item.comments)} ·
                            粉丝 {item.author_fans ? formatMetric(item.author_fans) : "—"}
                          </span>
                        }
                      />
                    </List.Item>
                  )}
                />
              )}
            </Modal>

            {selectedNote.tags?.length ? <div style={{ marginBottom: 12 }}>{selectedNote.tags.map((t) => <Tag key={t} color="blue">#{t}</Tag>)}</div> : null}

            <div style={{ marginBottom: 16 }}>
              <Text strong>正文</Text>
              <Paragraph style={{ marginTop: 4, color: token.colorTextSecondary }}>{selectedNote.content || "暂无正文。"}</Paragraph>
            </div>

            <Space wrap style={{ marginBottom: 16 }}>
              <Button
                icon={savedNoteIds.includes(selectedNote.note_id) ? <CheckOutlined /> : <DatabaseOutlined />}
                onClick={() => void handleSaveNote(selectedNote)}
                loading={savingNoteIds.includes(selectedNote.note_id)}
                disabled={savedNoteIds.includes(selectedNote.note_id)}
              >{savedNoteIds.includes(selectedNote.note_id) ? "已保存" : "保存到样本库"}</Button>
              <Button icon={<CommentOutlined />} onClick={() => void handlePreviewComments(selectedNote)}>{commentPreviewByNoteId[selectedNote.note_id] ? "收起评论" : "查看评论"}</Button>
              {getPreviewNoteUrl(selectedNote) && <Button type="primary" icon={<LinkOutlined />} href={getPreviewNoteUrl(selectedNote)} target="_blank" rel="noreferrer">打开原文</Button>}
            </Space>

            {commentPreviewErrors[selectedNote.note_id] && <Alert message={commentPreviewErrors[selectedNote.note_id]} type="error" showIcon style={{ marginBottom: 12 }} />}
            {commentPreviewByNoteId[selectedNote.note_id] && (
              <Card size="small" title="评论预览" style={{ background: token.colorFillQuaternary }}>
                {commentPreviewByNoteId[selectedNote.note_id].length === 0 ? <Text type="secondary">暂无评论</Text> : null}
                {commentPreviewByNoteId[selectedNote.note_id].filter((c) => !c.parent_comment_id).map((c) => (
                  <div key={c.comment_id} style={{ marginBottom: 12, paddingBottom: 8, borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
                    <Space><Text strong style={{ fontSize: 13 }}>{c.user_name}</Text><Text type="secondary" style={{ fontSize: 11 }}>{c.created_at_remote} · {c.like_count} likes</Text></Space>
                    <div style={{ color: token.colorTextSecondary, fontSize: 13, marginTop: 2 }}>{c.content}</div>
                    {getChildComments(selectedNote.note_id, c.comment_id).map((r) => (
                      <div key={r.comment_id} style={{ marginLeft: 20, marginTop: 6, paddingLeft: 8, borderLeft: `2px solid ${token.colorBorderSecondary}` }}>
                        <Space><Text strong style={{ fontSize: 12 }}>{r.user_name}</Text><Text type="secondary" style={{ fontSize: 11 }}>{r.like_count} likes</Text></Space>
                        <div style={{ color: token.colorTextTertiary, fontSize: 12 }}>{r.content}</div>
                      </div>
                    ))}
                  </div>
                ))}
              </Card>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
