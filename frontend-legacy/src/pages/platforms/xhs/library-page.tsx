import {
  BookOutlined,
  CheckSquareOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  DownOutlined,
  EditOutlined,
  EllipsisOutlined,
  ExperimentOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FireOutlined,
  HeartOutlined,
  LinkOutlined,
  LineChartOutlined,
  MessageOutlined,
  PictureOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  ShareAltOutlined,
  StarOutlined,
  StopOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  Dropdown,
  Empty,
  Image,
  Input,
  InputNumber,
  List,
  Modal,
  Pagination,
  Popconfirm,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { MenuProps } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  addNoteAsset,
  batchCreateDraftsFromNotes,
  batchRewriteNotes,
  batchTagNotes,
  createDraftFromNote,
  createTag,
  createViralTemplate,
  distillStyleFromLibrary,
  deleteNoteAsset,
  deleteSavedNote,
  deleteTag,
  downloadExportFile,
  exportSavedNotes,
  fetchSavedNote,
  fetchSavedNoteAssets,
  fetchSavedNoteComments,
  fetchSavedNotes,
  fetchTags,
  fetchAccounts,
  fetchXhsNoteDetail,
  fetchXhsNoteComments,
  refreshNoteMetrics,
  reorderNoteAssets,
  reviewDraft,
  rewriteDraftWithAi,
  saveXhsNotesToLibrary,
  updateTag,
} from "../../../lib/api";

type BatchItem = {
  note_id: number;
  source_note_id?: number;
  status: string;
  draft_id?: number;
  draft?: { id: number; title: string } | null;
  note?: { id: number; title?: string } | null;
  similarity?: number;
  warning?: string;
  error?: string;
  preflight?: {
    summary?: string;
    errors?: { key?: string; code?: string; message?: string; label?: string }[];
    warnings?: { key?: string; code?: string; message?: string; label?: string }[];
  } | null;
};
import { formatShanghaiTime } from "../../../lib/time";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import { PageHeader } from "../../../components/layout/app-shell";
import type { NoteAsset, NoteComment, NotesExportResponse, PlatformAccount, SavedNote, Tag as TagType } from "../../../types";
import type { BatchRewriteResult } from "../../../lib/api";
import { ViralAnalysisPanel } from "../../../components/insights/viral-analysis-panel";

const { Text, Paragraph } = Typography;
const UNAVAILABLE_KEY = "xhs-unavailable-notes";

function formatSavedTime(v: string): string { return formatShanghaiTime(v); }
function getRawNoteType(note: SavedNote): string { const t = note.raw_json?.model_type ?? note.raw_json?.type; return typeof t === "string" ? t : "note"; }
function getNotePublishTime(note: SavedNote): string {
  const raw = note.raw_json ?? {};
  const data = (raw.data && typeof raw.data === "object") ? raw.data as Record<string, unknown> : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const item = (items[0] && typeof items[0] === "object") ? items[0] as Record<string, unknown> : {};
  const card = (item.note_card && typeof item.note_card === "object") ? item.note_card as Record<string, unknown> : {};
  const ts = card.time ?? card.create_time ?? card.last_update_time ?? raw.time ?? raw.create_time;
  if (ts) {
    const n = typeof ts === "number" ? ts : Number(ts);
    if (Number.isFinite(n) && n > 0) return new Date(n > 1e12 ? n : n * 1000).toLocaleDateString("zh-CN");
  }
  return "";
}
function getNoteUrl(note: SavedNote): string {
  const raw = note.raw_json ?? {};
  for (const key of ["note_url", "url", "share_url"]) {
    const v = raw[key];
    if (typeof v === "string" && v.startsWith("http")) return v;
  }
  const data = (raw.data && typeof raw.data === "object") ? raw.data as Record<string, unknown> : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const item = (items[0] && typeof items[0] === "object") ? items[0] as Record<string, unknown> : {};
  const card = (item.note_card && typeof item.note_card === "object") ? item.note_card as Record<string, unknown> : {};
  for (const obj of [card, item]) {
    const xsec = obj.xsec_token;
    if (typeof xsec === "string" && xsec) {
      const src = (typeof obj.xsec_source === "string" ? obj.xsec_source : "") || "pc_feed";
      return `https://www.xiaohongshu.com/explore/${note.note_id}?xsec_token=${xsec}&xsec_source=${src}`;
    }
    for (const k of ["note_url", "url", "share_url"]) {
      const v = obj[k];
      if (typeof v === "string" && v.startsWith("http")) return v;
    }
  }
  return `https://www.xiaohongshu.com/explore/${note.note_id}`;
}
function getAuthorProfileUrl(note: SavedNote): string {
  const raw = note.raw_json ?? {};
  const directId = raw.author_id;
  if (typeof directId === "string" && directId) return `https://www.xiaohongshu.com/user/profile/${directId}`;
  const data = (raw.data && typeof raw.data === "object") ? raw.data as Record<string, unknown> : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const item = (items[0] && typeof items[0] === "object") ? items[0] as Record<string, unknown> : {};
  const card = (item.note_card && typeof item.note_card === "object") ? item.note_card as Record<string, unknown> : {};
  const user = (card.user && typeof card.user === "object") ? card.user as Record<string, unknown> : {};
  const uid = user.user_id ?? user.id;
  if (typeof uid === "string" && uid) return `https://www.xiaohongshu.com/user/profile/${uid}`;
  return "";
}
function getNoteTags(note: SavedNote): string[] {
  const raw = note.raw_json ?? {};
  const directList = raw.tag_list ?? raw.tags;
  if (Array.isArray(directList) && directList.length > 0) {
    return directList.map((t: unknown) => {
      if (typeof t === "string") return t;
      if (t && typeof t === "object" && "name" in (t as Record<string, unknown>)) return String((t as Record<string, unknown>).name);
      return "";
    }).filter(Boolean);
  }
  const data = (raw.data && typeof raw.data === "object") ? raw.data as Record<string, unknown> : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const item = (items[0] && typeof items[0] === "object") ? items[0] as Record<string, unknown> : {};
  const card = (item.note_card && typeof item.note_card === "object") ? item.note_card as Record<string, unknown> : {};
  const nestedList = card.tag_list;
  if (Array.isArray(nestedList) && nestedList.length > 0) {
    return nestedList.map((t: unknown) => {
      if (typeof t === "string") return t;
      if (t && typeof t === "object" && "name" in (t as Record<string, unknown>)) return String((t as Record<string, unknown>).name);
      return "";
    }).filter(Boolean);
  }
  return [];
}
function getNoteEngagement(note: SavedNote): { likes: number; collects: number; comments: number; shares: number } {
  const direct = {
    likes: Number(note.likes ?? 0),
    collects: Number(note.collects ?? 0),
    comments: Number(note.comments ?? 0),
    shares: Number(note.shares ?? 0),
  };
  if (direct.likes || direct.collects || direct.comments || direct.shares) return direct;
  const raw = note.raw_json ?? {};
  // Direct fields (from search results)
  const likes = Number(raw.liked_count ?? raw.likes ?? 0);
  const collects = Number(raw.collected_count ?? raw.collects ?? 0);
  const comments = Number(raw.comment_count ?? raw.comments ?? 0);
  const shares = Number(raw.share_count ?? raw.shares ?? 0);
  if (likes || collects || comments || shares) return { likes, collects, comments, shares };
  // Nested in data.items[0].note_card.interact_info
  const data = (raw.data && typeof raw.data === "object") ? raw.data as Record<string, unknown> : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const item = (items[0] && typeof items[0] === "object") ? items[0] as Record<string, unknown> : {};
  const card = (item.note_card && typeof item.note_card === "object") ? item.note_card as Record<string, unknown> : {};
  const info = (card.interact_info && typeof card.interact_info === "object") ? card.interact_info as Record<string, unknown> : {};
  return {
    likes: Number(info.liked_count ?? 0),
    collects: Number(info.collected_count ?? 0),
    comments: Number(info.comment_count ?? 0),
    shares: Number(info.share_count ?? 0),
  };
}
function rawString(note: SavedNote, keys: string[]): string { for (const k of keys) { const v = note.raw_json?.[k]; if (typeof v === "string" && v) return v; } return ""; }
function getSavedNoteCoverUrl(note: SavedNote): string { return note.cover_url || note.asset_urls?.[0] || rawString(note, ["cover_url", "image_url"]); }

export function XhsLibraryPage({ fixedSource }: { fixedSource?: "own" | "library" } = {}) {
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [notes, setNotes] = useState<SavedNote[]>([]);
  const [total, setTotal] = useState(0);
  /** Set by the server when the follower filter hid samples it could not judge. */
  const [filterNote, setFilterNote] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNote, setSelectedNote] = useState<SavedNote | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<NoteAsset[]>([]);
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isFetchingComments, setIsFetchingComments] = useState(false);
  const [backfillFailures, setBackfillFailures] = useState<
    Array<{ title: string; reason: string }>
  >([]);
  // Backfill runs slowly on purpose: XHS soft-blocks the detail endpoint when it
  // is hit in a tight loop, and the block looks like an empty note rather than an
  // error. These three states make that visible and resumable.
  const [backfillProgress, setBackfillProgress] = useState<{
    done: number;
    total: number;
    filled: number;
    status: "idle" | "running" | "cooling" | "paused";
    message: string;
  }>({ done: 0, total: 0, filled: 0, status: "idle", message: "" });
  const backfillCancelRef = useRef(false);
  const [unavailableIds, setUnavailableIds] = useState<Set<string>>(() => {    try {
      return new Set<string>(
        JSON.parse(window.localStorage.getItem(UNAVAILABLE_KEY) || "[]"),
      );
    } catch {
      return new Set<string>();
    }
  });
  const [isCreatingDraft, setIsCreatingDraft] = useState(false);
  const [availableTags, setAvailableTags] = useState<TagType[]>([]);
  const [newTagName, setNewTagName] = useState("");
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const [tagEditId, setTagEditId] = useState<number | null>(null);
  const [tagEditName, setTagEditName] = useState("");
  const [tagBusyId, setTagBusyId] = useState<number | null>(null);
  const [assetManagerOpen, setAssetManagerOpen] = useState(false);
  const [newAssetUrl, setNewAssetUrl] = useState("");
  const [assetBusyId, setAssetBusyId] = useState<number | null>(null);
  const [isCommentsOpen, setIsCommentsOpen] = useState(false);
  const [comments, setComments] = useState<NoteComment[]>([]);
  const [commentsTotal, setCommentsTotal] = useState(0);
  const [commentsPage, setCommentsPage] = useState(1);
  const [isCommentsLoading, setIsCommentsLoading] = useState(false);
  const [commentsError, setCommentsError] = useState<string | null>(null);
  const [keywordFilter, setKeywordFilter] = useState("");
  const [selectedTagFilter, setSelectedTagFilter] = useState("");
  const [hasAssetsFilter, setHasAssetsFilter] = useState(false);
  const [hasCommentsFilter, setHasCommentsFilter] = useState(false);
  const [contentFilter, setContentFilter] = useState<"ready" | "empty" | "">("");

  const visibleNotes = contentFilter
    ? notes.filter((note) => {
        const hasContent = (note.content || "").trim().length >= 100;
        return contentFilter === "ready" ? hasContent : !hasContent;
      })
    : notes;
  const [sourceFilter, setSourceFilter] = useState<"all" | "own" | "library">(fixedSource ?? "all");
  const [maxFansFilter, setMaxFansFilter] = useState<number | null>(null);
  const [minLikesFilter, setMinLikesFilter] = useState<number | null>(null);
  const [minRatioFilter, setMinRatioFilter] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<"created_at" | "likes" | "like_fan_ratio" | "engagement_rate">("created_at");
  const [viewMode, setViewMode] = useState<string>("card");
  const [selectedNoteIds, setSelectedNoteIds] = useState<number[]>([]);
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [rewriteAccounts, setRewriteAccounts] = useState<PlatformAccount[]>([]);
  const [ownAccounts, setOwnAccounts] = useState<PlatformAccount[]>([]);
  const [rewriteAccountId, setRewriteAccountId] = useState<number | null>(null);
  const [rewriteInstruction, setRewriteInstruction] = useState("");
  const [rewriteBusy, setRewriteBusy] = useState(false);
  const [rewriteResult, setRewriteResult] = useState<BatchRewriteResult | null>(null);
  const [rewriteAdopted, setRewriteAdopted] = useState<number[]>([]);
  const [rewriteBusyDraftId, setRewriteBusyDraftId] = useState<number | null>(null);
  const [batchTagId, setBatchTagId] = useState<string>("");
  const [isBatchWorking, setIsBatchWorking] = useState(false);
  const [latestExport, setLatestExport] = useState<NotesExportResponse | null>(null);

  const selectedNoteIdSet = new Set(selectedNoteIds);

  async function loadNotes(overrideFilters?: { q?: string; tag_id?: number; has_assets?: boolean; has_comments?: boolean; source?: "all" | "own" | "library"; max_fans?: number; min_likes?: number; min_like_fan_ratio?: number; sort_by?: "created_at" | "likes" | "like_fan_ratio" | "engagement_rate" }, targetPage = page, targetPageSize = pageSize) {
    setIsLoading(true); setError(null);
    const f = {
      ...(overrideFilters ?? {
        q: keywordFilter.trim() || undefined,
        tag_id: selectedTagFilter ? Number(selectedTagFilter) : undefined,
        has_assets: hasAssetsFilter || undefined,
        has_comments: hasCommentsFilter || undefined,
        source: sourceFilter === "all" ? undefined : sourceFilter,
        max_fans: maxFansFilter ?? undefined,
        min_likes: minLikesFilter ?? undefined,
        min_like_fan_ratio: minRatioFilter ?? undefined,
        sort_by: sortBy,
      }),
      ...(fixedSource ? { source: fixedSource } : {}),
    };
    try {
      const r = await fetchSavedNotes({ platform: "xhs", page: targetPage, page_size: targetPageSize, ...f });
      setNotes(r.items); setTotal(r.total);
      setFilterNote(r.filter_note ?? null);
      const ids = new Set(r.items.map((n) => n.id));
      setSelectedNoteIds((c) => c.filter((id) => ids.has(id)));
    } catch { setError(fixedSource === "library" ? "样本库加载失败。" : fixedSource === "own" ? "我的笔记加载失败。" : "笔记库加载失败。"); } finally { setIsLoading(false); }
  }

  useEffect(() => {
    // 支持从竞品监控 / 其他板块带 q 参数进入（如 ?q=笔记id 或 作者名）
    const params = new URLSearchParams(window.location.search);
    const incoming = (params.get("q") || "").trim();
    const incomingSource = params.get("source");
    if (!fixedSource && (incomingSource === "own" || incomingSource === "library")) {
      setSourceFilter(incomingSource);
    }
    const source = fixedSource ?? (incomingSource === "own" || incomingSource === "library" ? incomingSource : undefined);
    if (incoming) {
      setKeywordFilter(incoming);
      void loadNotes({ q: incoming, source });
    } else {
      void loadNotes(source ? { source } : undefined);
    }
    void loadTags();
    if (fixedSource === "own") {
      void fetchAccounts("xhs")
        .then((items) => setOwnAccounts(items))
        .catch(() => setOwnAccounts([]));
    }
  }, []);

  function clearFilters() {
    setKeywordFilter(""); setSelectedTagFilter(""); setHasAssetsFilter(false); setHasCommentsFilter(false);
    setContentFilter("");
    setSourceFilter(fixedSource ?? "all");
    setMaxFansFilter(null); setMinLikesFilter(null); setMinRatioFilter(null); setSortBy("created_at");
    setPage(1);
    void loadNotes({}, 1, pageSize);
  }
  function toggleNoteSelection(id: number) { setSelectedNoteIds((c) => c.includes(id) ? c.filter((i) => i !== id) : [...c, id]); }
  function toggleVisibleSelection() { if (!notes.length) return; const vis = notes.map((n) => n.id); const allSel = vis.every((id) => selectedNoteIdSet.has(id)); setSelectedNoteIds((c) => allSel ? c.filter((id) => !vis.includes(id)) : Array.from(new Set([...c, ...vis]))); }
  function clearSelection() { setSelectedNoteIds([]); }

  async function loadTags() { try { const r = await fetchTags(); setAvailableTags(r.items); } catch { setAvailableTags([]); } }

  async function openDetail(note: SavedNote) {
    setIsDetailOpen(true); setSelectedNote(note); setDetailError(null); resetComments(); setIsDetailLoading(true);
    try { const [d, a] = await Promise.all([fetchSavedNote(note.id), fetchSavedNoteAssets(note.id)]); setSelectedNote(d); setSelectedAssets(a.items); }
    catch { setDetailError("笔记详情加载失败。"); } finally { setIsDetailLoading(false); }
  }
  function closeDetail() { setIsDetailOpen(false); setDetailError(null); setSelectedAssets([]); resetComments(); }
  function resetComments() { setIsCommentsOpen(false); setComments([]); setCommentsTotal(0); setCommentsPage(1); setIsCommentsLoading(false); setCommentsError(null); }

  async function syncNoteMetrics() {
    if (!selectedNote) return;
    setIsSyncing(true);
    try {
      const accounts = await fetchAccounts("xhs");
      const pcAccounts = accounts.filter((a) => a.platform === "xhs" && a.sub_type === "pc");
      const preferred = pcAccounts.find((a) => a.id === selectedNote.platform_account_id) ?? pcAccounts[0];
      if (!preferred) {
        message.warning("没有可用的 PC 账号，无法同步数据。");
        return;
      }
      const url = getNoteUrl(selectedNote);
      const detail = await fetchXhsNoteDetail({ account_id: preferred.id, url });
      const result = await saveXhsNotesToLibrary({ account_id: preferred.id, notes: [detail] });
      const updated = result.items[0] ?? null;
      if (updated) {
        setSelectedNote(updated);
        replaceNoteInList(updated);
        await loadNotes();
      }
      message.success(
        `已同步最新数据：赞 ${updated?.likes ?? 0} · 藏 ${updated?.collects ?? 0} · 评 ${updated?.comments ?? 0}`,
      );
    } catch {
      message.error("同步失败，请确认 PC 账号登录态有效。");
    } finally {
      setIsSyncing(false);
    }
  }

  async function copySelectedNote() {
    if (!selectedNote) return;
    try {
      await navigator.clipboard.writeText(`${selectedNote.title}\n\n${selectedNote.content}`.trim());
      message.success("已复制标题和正文。");
    } catch {
      message.error("复制失败。");
    }
  }

  async function fetchNoteComments() {
    if (!selectedNote) return;
    setIsFetchingComments(true);
    try {
      const accounts = await fetchAccounts("xhs");
      const pcAccounts = accounts.filter((a) => a.platform === "xhs" && a.sub_type === "pc");
      const preferred =
        pcAccounts.find((a) => a.id === selectedNote.platform_account_id) ?? pcAccounts[0];
      if (!preferred) {
        message.warning("没有可用的 PC 账号，无法抓取评论。");
        return;
      }
      const url = getNoteUrl(selectedNote);
      const result = await fetchXhsNoteComments({ account_id: preferred.id, note_url: url });
      setComments(result.items);
      setCommentsTotal(result.total ?? 0);
      setIsCommentsOpen(true);
      message.success(
        result.total ? `已抓取 ${result.total} 条评论。` : "抓取完成，但没有读到评论（可能为关闭评论）。",
      );
    } catch {
      message.error("抓取评论失败，请确认 PC 账号登录态有效。");
    } finally {
      setIsFetchingComments(false);
    }
  }

  async function createDraft(intent: "rewrite" | "publish") {
    if (!selectedNote) return; setIsCreatingDraft(true);
    try {
      const d = await createDraftFromNote({ platform: "xhs", source_note_id: selectedNote.id, intent });
      message.success(`已创建草稿 #${d.id}，正在跳转...`);
      setTimeout(() => navigate("/platforms/xhs/write/drafts"), 600);
    }
    catch { message.error("草稿创建失败。"); } finally { setIsCreatingDraft(false); }
  }

  async function addToDrafts() {
    if (!selectedNote) return; setIsCreatingDraft(true);
    try {
      const d = await createDraftFromNote({ platform: "xhs", source_note_id: selectedNote.id, intent: "rewrite" });
      message.success(`已加入草稿工坊，草稿 #${d.id}。`);
    }
    catch { message.error("加入草稿工坊失败。"); } finally { setIsCreatingDraft(false); }
  }

  async function handleDeleteNote(note: SavedNote) {
    Modal.confirm({
      title: "删除这条笔记？",
      content: "相关素材、评论和标签关系也会一起删除，删除后不可恢复。",
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteSavedNote(note.id);
          setNotes((c) => c.filter((n) => n.id !== note.id));
          setSelectedNoteIds((c) => c.filter((id) => id !== note.id));
          setTotal((c) => Math.max(0, c - 1));
          if (selectedNote?.id === note.id) closeDetail();
          message.success("已删除笔记。");
        } catch { message.error("删除失败。"); }
      },
    });
  }

  function selectedNoteHasTag(tagId: number): boolean { return Boolean(selectedNote?.tags?.some((t) => t.id === tagId)); }
  function replaceNoteInList(u: SavedNote) { setNotes((c) => c.map((n) => n.id === u.id ? u : n)); }
  function replaceNotesInList(us: SavedNote[]) { const m = new Map(us.map((n) => [n.id, n])); setNotes((c) => c.map((n) => m.get(n.id) ?? n)); if (selectedNote) { const u = m.get(selectedNote.id); if (u) setSelectedNote(u); } }

  async function applyBatchTag(mode: "add" | "remove") {
    if (!selectedNoteIds.length) { message.warning("请先选择笔记。"); return; }
    if (!batchTagId) { message.warning("请选择一个标签。"); return; }
    setIsBatchWorking(true);
    try { const r = await batchTagNotes({ note_ids: selectedNoteIds, tag_ids: [Number(batchTagId)], mode }); replaceNotesInList(r.items); message.success(mode === "add" ? `已添加标签 (${r.updated_count})` : `已移除标签 (${r.updated_count})`); }
    catch { message.error("批量标签操作失败。"); } finally { setIsBatchWorking(false); }
  }

  async function createBatchRewriteDrafts() {
    if (!selectedNoteIds.length) { message.warning("请先选择笔记。"); return; }
    setIsBatchWorking(true);
    try { const r = await batchCreateDraftsFromNotes({ note_ids: selectedNoteIds, intent: "rewrite" }); message.success(`已创建 ${r.created_count} 个改写草稿。`); }
    catch { message.error("批量创建草稿失败。"); } finally { setIsBatchWorking(false); }
  }

  async function refreshSelectedMetrics() {
    if (!selectedNoteIds.length) { message.warning("请先选择笔记。"); return; }
    setIsBatchWorking(true);
    try {
      const r = await refreshNoteMetrics(selectedNoteIds);
      replaceNotesInList(
      ((r.items ?? []) as BatchItem[])
        .flatMap((item) => (item.note ? [item.note as unknown as SavedNote] : [])),
    );
      const errors = ((r.items ?? []) as BatchItem[])
        .filter((item: BatchItem) => item.status === "failed")
        .map((item: BatchItem) => item.error)
        .filter(Boolean)
        .slice(0, 2);
      const summary = `指标刷新：成功 ${r.updated} 条，失败 ${r.failed} 条。${errors.length ? `原因：${errors.join("；")}` : ""}`;
      if (Number(r.failed) > 0) message.warning(summary);
      else message.success(summary);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "刷新指标失败，请确认 PC 账号可用。");
    } finally {
      setIsBatchWorking(false);
    }
  }

  async function backfillContents() {
    if (!selectedNoteIds.length) {
      message.warning("请先选择样本。");
      return;
    }
    if (!window.confirm(
      "补全正文会逐篇请求小红书详情接口。为避免被限流，每篇之间会间隔约 10 秒，且连续失败时会自动冷却。\n\n过程中可以随时点「停止」，已完成的会保留。继续？",
    )) {
      return;
    }
    setIsBatchWorking(true);
    setBackfillFailures([]);
    backfillCancelRef.current = false;

    let filled = 0;
    let rateLimitStreak = 0;
    const failures: Array<{ title: string; reason: string }> = [];
    try {
      const accounts = (await fetchAccounts("xhs")).filter(
        (account) => account.sub_type === "pc" || account.sub_type === "creator",
      );
      const pcAccount = accounts[0];
      if (!pcAccount) {
        message.warning("没有可用的 PC 账号，无法补全正文。");
        return;
      }
      const targets = notes.filter(
        (n) =>
          selectedNoteIds.includes(n.id) &&
          (n.content || "").trim().length < 50 &&
          !unavailableIds.has(String(n.id)),
      );
      if (!targets.length) {
        message.warning("选中的笔记都已有正文，或已标记为不可用。");
        return;
      }

      setBackfillProgress({
        done: 0,
        total: targets.length,
        filled: 0,
        status: "running",
        message: `准备补全 ${targets.length} 篇`,
      });

      for (let index = 0; index < targets.length; index += 1) {
        if (backfillCancelRef.current) {
          setBackfillProgress((prev) => ({
            ...prev,
            status: "paused",
            message: `已停止：完成 ${filled} 篇，剩余 ${targets.length - index} 篇未处理`,
          }));
          break;
        }

        const note = targets[index];
        setBackfillProgress((prev) => ({
          ...prev,
          done: index,
          filled,
          status: "running",
          message: `正在补全第 ${index + 1}/${targets.length} 篇：${note.title || note.note_id}`,
        }));

        try {
          const detail = await fetchXhsNoteDetail({
            account_id: pcAccount.id,
            url: getNoteUrl(note),
          });
          if ((detail.content || "").trim().length < 20) {
            failures.push({ title: note.title || note.note_id, reason: "详情返回空正文" });
            rateLimitStreak += 1;
          } else {
            await saveXhsNotesToLibrary({ account_id: pcAccount.id, notes: [detail] });
            filled += 1;
            rateLimitStreak = 0;
          }
        } catch (error) {
          const status = (error as { response?: { status?: number } })?.response?.status;
          const reason =
            (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
            "请求失败";
          // 429/502 with a "cannot browse" message means XHS is throttling us,
          // not that this note is dead. Back off instead of hammering on.
          const throttled = status === 429 || (status === 502 && /无法浏览|限流/.test(reason));
          failures.push({
            title: note.title || note.note_id,
            reason: throttled ? `被限流：${reason}` : reason,
          });
          if (throttled) {
            rateLimitStreak += 1;
          } else {
            rateLimitStreak = 0;
          }
        }

        if (index < targets.length - 1) {
          // Exponential backoff: 10s normally, doubling while XHS keeps refusing,
          // capped so a long batch still finishes.
          const waitMs = rateLimitStreak > 0
            ? Math.min(120_000, 10_000 * 2 ** Math.min(rateLimitStreak, 4))
            : 10_000;
          if (rateLimitStreak >= 3) {
            setBackfillProgress((prev) => ({
              ...prev,
              status: "cooling",
              message: `连续 ${rateLimitStreak} 次被限流，冷却 ${Math.round(waitMs / 1000)} 秒后再继续…`,
            }));
          }
          await new Promise((resolve) => setTimeout(resolve, waitMs));
        }
      }

      await loadNotes();
      setBackfillFailures(failures);
      const remaining = targets.length - filled - failures.length;
      const summary = `补全正文：成功 ${filled} 篇${
        failures.length ? `，失败 ${failures.length} 篇` : ""
      }${remaining > 0 ? `，未处理 ${remaining} 篇（可重新选中继续）` : ""}。${
        filled ? "现在可以用它们蒸馏 Skill 了。" : ""
      }`;
      if (failures.length || remaining > 0) message.warning(summary);
      else message.success(summary);
      setBackfillProgress((prev) => ({
        ...prev,
        done: targets.length,
        filled,
        status: "idle",
        message: "",
      }));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "补全正文失败，请确认 PC 账号登录态有效。");
      setBackfillProgress((prev) => ({ ...prev, status: "idle" }));
    } finally {
      setIsBatchWorking(false);
    }
  }

  async function markUnavailable() {
    if (!selectedNoteIds.length) return;
    setIsBatchWorking(true);
    try {
      const marked = new Set<string>(
        JSON.parse(window.localStorage.getItem(UNAVAILABLE_KEY) || "[]"),
      );
      for (const id of selectedNoteIds) {
        marked.add(String(id));
      }
      window.localStorage.setItem(UNAVAILABLE_KEY, JSON.stringify([...marked]));
      setUnavailableIds(marked);
      message.success(
        `已标记 ${selectedNoteIds.length} 条为「正文不可用」，补全时会自动跳过。`,
      );
    } finally {
      setIsBatchWorking(false);
    }
  }

  async function openBatchRewrite() {
    if (!selectedNoteIds.length) {
      message.warning("请先选择笔记。");
      return;
    }
    if (selectedNoteIds.length > 5) {
      message.warning("批量 AI 改写一次最多 5 条，请减少选择。");
      return;
    }
    setRewriteResult(null);
    setRewriteInstruction("");
    setRewriteAdopted([]);
    try {
      const loaded = (await fetchAccounts("xhs")).filter(
        (account) => account.sub_type === "pc" || account.sub_type === "creator",
      );
      setRewriteAccounts(loaded);
      setRewriteAccountId(loaded[0]?.id ?? null);
    } catch {
      setRewriteAccounts([]);
      setRewriteAccountId(null);
    }
    setRewriteOpen(true);
  }

  async function submitBatchRewrite() {
    if (!selectedNoteIds.length) return;
    setRewriteBusy(true);
    try {
      const result = await batchRewriteNotes({
        note_ids: selectedNoteIds.slice(0, 5),
        account_id: rewriteAccountId,
        instruction: rewriteInstruction.trim(),
      });
      setRewriteResult(result);
      setRewriteAdopted([]);
      const summary = `AI 改写完成：成功 ${result.created_count} 条，失败 ${result.failed_count} 条。请在草稿工坊检查。`;
      if ((result.failed_count ?? 0) > 0) message.warning(summary);
      else message.success(summary);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "批量 AI 改写失败，请确认模型和风险开关。");
    } finally {
      setRewriteBusy(false);
    }
  }

  async function toggleRewriteAdopt(draftId: number) {
    const nextStatus = rewriteAdopted.includes(draftId) ? "pending" : "adopted";
    try {
      await reviewDraft(draftId, nextStatus);
      setRewriteAdopted((current) =>
        current.includes(draftId) ? current.filter((id) => id !== draftId) : [...current, draftId],
      );
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "更新采用状态失败");
    }
  }

  async function rewriteResultDraft(draftId: number) {
    setRewriteBusyDraftId(draftId);
    try {
      const draft = await rewriteDraftWithAi({
        draft_id: draftId,
        account_id: rewriteAccountId,
        instruction: "再换一个角度重写，降低与原文的相似度，保留账号语气。",
      });
      setRewriteResult((current) =>
        current
          ? ({
              ...current,
              items: current.items.map((item) =>
                item.draft?.id === draftId ? { ...item, draft, warning: "" } : item,
              ),
            } as BatchRewriteResult)
          : current,
      );
      message.success("已重写这一条");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "重写失败");
    } finally {
      setRewriteBusyDraftId(null);
    }
  }

  async function discardRewriteDraft(draftId: number) {
    setRewriteBusyDraftId(draftId);
    try {
      await reviewDraft(draftId, "discarded");
      setRewriteAdopted((current) => current.filter((id) => id !== draftId));
      setRewriteResult((current) =>
        current
          ? {
              ...current,
              created_count: Math.max(0, (current.created_count ?? 0) - 1),
              items: current.items.filter((item) => item.draft?.id !== draftId),
            }
          : current,
      );
      message.success("已标记为废弃，草稿仍保留在草稿工坊");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "废弃失败");
    } finally {
      setRewriteBusyDraftId(null);
    }
  }

  async function createTemplateFromSelection() {
    if (!selectedNoteIds.length || selectedNoteIds.length > 3) {
      message.warning("请选择 1–3 条笔记生成标题/要点模板。");
      return;
    }
    setIsBatchWorking(true);
    try {
      const template = await createViralTemplate({ note_ids: selectedNoteIds });
      message.success(`已生成标题/要点模板「${template.name}」，可在「结构模板」中查看。`);
    } catch {
      message.error("生成标题/要点模板失败。");
    } finally {
      setIsBatchWorking(false);
    }
  }

  async function distillSelection() {
    if (selectedNoteIds.length < 3) {
      message.warning("请选择 3–20 条有正文的样本再蒸馏。");
      return;
    }
    setIsBatchWorking(true);
    try {
      const profile = await distillStyleFromLibrary(
        selectedNoteIds,
        `样本库风格 ${new Date().toLocaleDateString("zh-CN")}`,
        true,
      );
      message.success(
        `已蒸馏出写法「${profile.name}」（${profile.works_count} 篇）。去「创作 Skill」查看并应用。`,
      );
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "蒸馏失败，请确认已配置默认文本模型。");
    } finally {
      setIsBatchWorking(false);
    }
  }

  async function exportSelectedNotes(format: "json" | "csv") {
    if (!selectedNoteIds.length) { message.warning("请先选择笔记。"); return; }
    setIsBatchWorking(true);
    try { const r = await exportSavedNotes({ note_ids: selectedNoteIds, format }); setLatestExport(r); message.success(`已导出 ${r.exported_count} 条笔记。`); }
    catch { message.error("导出失败。"); } finally { setIsBatchWorking(false); }
  }

  async function batchDeleteNotes() {
    if (!selectedNoteIds.length) return;
    setIsBatchWorking(true);
    try {
      for (const id of selectedNoteIds) {
        await deleteSavedNote(id);
      }
      setNotes((c) => c.filter((n) => !selectedNoteIds.includes(n.id)));
      setTotal((c) => Math.max(0, c - selectedNoteIds.length));
      message.success(`已删除 ${selectedNoteIds.length} 条笔记。`);
      setSelectedNoteIds([]);
    } catch { message.error("批量删除失败。"); }
    finally { setIsBatchWorking(false); }
  }

  async function downloadLatestExport() {
    if (!latestExport) return; setIsBatchWorking(true);
    try { await downloadExportFile(latestExport.download_url, latestExport.file_name); message.success(`已下载：${latestExport.file_name}`); }
    catch { message.error("下载失败。"); } finally { setIsBatchWorking(false); }
  }

  async function toggleSelectedTag(tag: TagType) {
    if (!selectedNote) return;
    const mode = selectedNoteHasTag(tag.id) ? "remove" : "add";
    try { const r = await batchTagNotes({ note_ids: [selectedNote.id], tag_ids: [tag.id], mode }); const u = r.items[0]; setSelectedNote(u); replaceNoteInList(u); }
    catch { message.error("标签更新失败。"); }
  }

  async function createAndAssignTag() {
    if (!selectedNote) return; const name = newTagName.trim(); if (!name) { message.warning("请输入标签名称。"); return; }
    try { const c = await createTag({ name, color: "#111111" }); setAvailableTags((t) => [...t, c]); setNewTagName(""); const r = await batchTagNotes({ note_ids: [selectedNote.id], tag_ids: [c.id], mode: "add" }); const u = r.items[0]; setSelectedNote(u); replaceNoteInList(u); }
    catch { message.error("标签创建失败。"); }
  }

  function startEditTag(tag: TagType) {
    setTagEditId(tag.id);
    setTagEditName(tag.name);
  }

  async function saveTagName(tag: TagType) {
    const name = tagEditName.trim();
    if (!name) {
      message.warning("标签名不能为空");
      return;
    }
    setTagBusyId(tag.id);
    try {
      const updated = await updateTag(tag.id, { name });
      setAvailableTags((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
      setTagEditId(null);
      setTagEditName("");
      message.success("标签已重命名");
    } catch {
      message.error("标签重命名失败");
    } finally {
      setTagBusyId(null);
    }
  }

  async function removeTag(tag: TagType) {
    setTagBusyId(tag.id);
    try {
      await deleteTag(tag.id);
      setAvailableTags((items) => items.filter((item) => item.id !== tag.id));
      if (selectedTagFilter === String(tag.id)) {
        setSelectedTagFilter("");
      }
      message.success(`已删除标签「${tag.name}」`);
    } catch {
      message.error("标签删除失败");
    } finally {
      setTagBusyId(null);
    }
  }

  async function addAssetFromUrl() {
    if (!selectedNote) return;
    const url = newAssetUrl.trim();
    if (!url) {
      message.warning("请输入图片链接");
      return;
    }
    setAssetBusyId(-1);
    try {
      const asset = await addNoteAsset(selectedNote.id, {
        asset_type: "image",
        url,
      });
      setSelectedAssets((items) => [...items, asset]);
      setNewAssetUrl("");
      message.success("素材已添加");
    } catch {
      message.error("添加素材失败");
    } finally {
      setAssetBusyId(null);
    }
  }

  async function removeSelectedAsset(asset: NoteAsset) {
    if (!selectedNote) return;
    setAssetBusyId(asset.id);
    try {
      await deleteNoteAsset(selectedNote.id, asset.id);
      setSelectedAssets((items) => items.filter((item) => item.id !== asset.id));
      message.success("素材已删除");
    } catch {
      message.error("删除素材失败");
    } finally {
      setAssetBusyId(null);
    }
  }

  async function moveAsset(asset: NoteAsset, direction: -1 | 1) {
    if (!selectedNote) return;
    const index = selectedAssets.findIndex((item) => item.id === asset.id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= selectedAssets.length) return;
    const next = [...selectedAssets];
    [next[index], next[target]] = [next[target], next[index]];
    setSelectedAssets(next);
    try {
      await reorderNoteAssets(
        selectedNote.id,
        next.map((item) => item.id),
      );
    } catch {
      setSelectedAssets(selectedAssets);
      message.error("调整素材顺序失败");
    }
  }

  async function loadComments(page = 1) {
    if (!selectedNote) return; setIsCommentsLoading(true); setCommentsError(null);
    try { const r = await fetchSavedNoteComments(selectedNote.id, page); setComments((c) => (page === 1 ? r.items : [...c, ...r.items])); setCommentsTotal(r.total ?? 0); setCommentsPage(page); }
    catch { setCommentsError("评论加载失败。"); } finally { setIsCommentsLoading(false); }
  }

  function toggleComments() { const next = !isCommentsOpen; setIsCommentsOpen(next); if (next && selectedNote && comments.length === 0) void loadComments(1); }
  const topLevelComments = comments.filter((c) => !c.parent_comment_id);
  function childComments(pid: string) { return comments.filter((c) => c.parent_comment_id === pid); }

  const tableColumns: ColumnsType<SavedNote> = fixedSource === "own"
    ? [
        { title: "标题", dataIndex: "title", ellipsis: true, render: (t: string, n) => (
          <Space size={4}>
            <a onClick={() => void openDetail(n)}>{t || "未命名"}</a>
            <Tag color="blue">我的笔记</Tag>
          </Space>
        ) },
        { title: "发布账号", dataIndex: "platform_account_id", width: 140, render: (id?: number) => {
          if (!id) return "-";
          const account = ownAccounts.find((item) => item.id === id);
          return account?.nickname || `账号 #${id}`;
        } },
        { title: "发布时间", key: "publish_time", width: 160, render: (_, n) => getNotePublishTime(n) || formatSavedTime(n.created_at) },
        { title: "状态", key: "status", width: 100, render: () => <Tag color="green">已发布</Tag> },
        {
          title: "互动",
          key: "engagement",
          width: 200,
          render: (_, n) => {
            const eng = getNoteEngagement(n);
            return `赞 ${eng.likes} / 藏 ${eng.collects} / 评 ${eng.comments} / 转 ${eng.shares}`;
          },
        },
        { title: "笔记 ID", dataIndex: "note_id", width: 140, ellipsis: true },
        { title: "标签", key: "tags", width: 160, render: (_, n) => n.tags?.length ? <Space size={4} wrap>{n.tags.map((t) => <Tag key={t.id} color="blue">{t.name}</Tag>)}</Space> : <Text type="secondary">-</Text> },
        {
          title: "操作",
          key: "actions",
          width: 170,
          render: (_, n) => (
            <Space size={2}>
              <Link
                to={`/platforms/xhs/dashboard/review?account_id=${n.platform_account_id ?? ""}&note_id=${encodeURIComponent(n.note_id)}`}
                onClick={(event) => event.stopPropagation()}
              >
                <Button type="link" size="small">看复盘</Button>
              </Link>
              <Button type="text" danger icon={<DeleteOutlined />} size="small" onClick={(e) => { e.stopPropagation(); void handleDeleteNote(n); }} />
            </Space>
          ),
        },
      ]
    : [
        { title: "标题", dataIndex: "title", ellipsis: true, render: (t: string, n) => (
          <Space size={4}>
            <a onClick={() => void openDetail(n)}>{t || "未命名"}</a>
            {n.source_type === "publish" ? <Tag color="green">已发布</Tag> : n.source_type === "creator" ? <Tag color="blue">我的笔记</Tag> : n.raw_json?.origin === "publish" ? <Tag color="green">已发布</Tag> : null}
          </Space>
        ) },
        { title: "作者", dataIndex: "author_name", width: 120 },
        { title: "粉丝", dataIndex: "author_fans", width: 90, render: (v?: number) => (v ? v.toLocaleString() : "-") },
        { title: "点赞", dataIndex: "likes", width: 90, render: (v?: number) => (v ? v.toLocaleString() : "-") },
        { title: "赞粉比", dataIndex: "like_fan_ratio", width: 90, render: (v?: number) => (v ? v.toFixed(2) : "-") },
        { title: "笔记 ID", dataIndex: "note_id", width: 140, ellipsis: true },
        { title: "保存时间", dataIndex: "created_at", width: 160, render: (v: string) => formatSavedTime(v) },
        { title: "标签", key: "tags", width: 180, render: (_, n) => n.tags?.length ? <Space size={4} wrap>{n.tags.map((t) => <Tag key={t.id} color="blue">{t.name}</Tag>)}</Space> : <Text type="secondary">-</Text> },
        { title: "操作", key: "actions", width: 80, render: (_, n) => <Button type="text" danger icon={<DeleteOutlined />} size="small" onClick={(e) => { e.stopPropagation(); void handleDeleteNote(n); }} /> },
      ];

  // 「我的笔记」视图不允许蒸馏自己的风格；只有外部样本可以。
  const isOwnSource = fixedSource === "own";

  const batchMenuItems: MenuProps["items"] = [
    {
      key: "refresh",
      icon: <SyncOutlined />,
      label: selectedNoteIds.length > 10 ? "刷新指标（最多 10 条）" : "刷新指标",
      disabled: isBatchWorking || !selectedNoteIds.length || selectedNoteIds.length > 10,
    },
    {
      key: "template",
      icon: <FileTextOutlined />,
      label: isOwnSource
        ? "生成标题/要点模板（最多 3 条）"
        : selectedNoteIds.length > 3
          ? "生成标题/要点模板（最多 3 条）"
          : "生成标题/要点模板",
      disabled: isBatchWorking || !selectedNoteIds.length || selectedNoteIds.length > 3,
    },
    { type: "divider" },
    {
      key: "backfill",
      icon: <FileTextOutlined />,
      label: `补全正文（${selectedNoteIds.length} 条）`,
      disabled: isBatchWorking || !selectedNoteIds.length,
    },
    {
      key: "unavailable",
      icon: <StopOutlined />,
      label: "标记正文不可用",
      disabled: isBatchWorking || !selectedNoteIds.length,
    },
    // 蒸馏是「向外学」：只对外部样本开放。用自己发的笔记蒸馏自己的风格
    // 逻辑上不成立，产物也无法用来指导写作。
    ...(isOwnSource
      ? []
      : [
          {
            key: "distill",
            icon: <ExperimentOutlined />,
            label:
              selectedNoteIds.length < 3
                ? "蒸馏成 Skill（需选 3 篇以上）"
                : `蒸馏成 Skill（${selectedNoteIds.length} 篇）`,
            disabled: isBatchWorking || selectedNoteIds.length < 3 || selectedNoteIds.length > 20,
          },
        ]),
    { type: "divider" },
    {
      key: "json",
      icon: <DownloadOutlined />,
      label: "导出 JSON",
      disabled: isBatchWorking || !selectedNoteIds.length,
    },
    {
      key: "csv",
      icon: <DownloadOutlined />,
      label: "导出 CSV",
      disabled: isBatchWorking || !selectedNoteIds.length,
    },
    ...(latestExport
      ? [
          {
            key: "download",
            icon: <DownloadOutlined />,
            label: "下载上次导出",
            disabled: isBatchWorking,
          },
        ]
      : []),
    { type: "divider" },
    {
      key: "delete",
      icon: <DeleteOutlined />,
      label: "批量删除",
      danger: true,
      disabled: isBatchWorking || !selectedNoteIds.length,
    },
  ];

  function handleBatchMenu(key: string) {
    if (key === "refresh") void refreshSelectedMetrics();
    if (key === "template") void createTemplateFromSelection();
    if (key === "backfill") void backfillContents();
    if (key === "unavailable") void markUnavailable();
    if (key === "distill") void distillSelection();
    if (key === "json") void exportSelectedNotes("json");
    if (key === "csv") void exportSelectedNotes("csv");
    if (key === "download") void downloadLatestExport();
    if (key === "delete") {
      Modal.confirm({
        title: `删除选中的 ${selectedNoteIds.length} 条笔记？`,
        content: "相关素材、评论和标签关系会一起删除，删除后不可恢复。",
        okText: "确认删除",
        okButtonProps: { danger: true },
        cancelText: "取消",
        onOk: () => batchDeleteNotes(),
      });
    }
  }

  const hasActiveFilters =
    Boolean(keywordFilter) ||
    Boolean(selectedTagFilter) ||
    hasAssetsFilter ||
    hasCommentsFilter ||
    Boolean(contentFilter) ||
    maxFansFilter !== null ||
    minLikesFilter !== null ||
    minRatioFilter !== null ||
    sourceFilter !== (fixedSource ?? "all");

  return (
    <div>
      <PageHeader
        eyebrow={fixedSource === "own" ? "Owned Notes" : "Assets"}
        title={fixedSource === "own" ? "我的笔记" : fixedSource === "library" ? "样本库" : "笔记库"}
        description={
          fixedSource === "own"
            ? "只看自己发布过的笔记。复盘去「总览 → 复盘」；外部参考去「素材 → 样本库」。"
            : fixedSource === "library"
              ? "只看外部样本。选中 3 篇以上有正文的样本可「蒸馏成 Skill」；自己的复盘去「总览 → 复盘」。"
              : "同一张表里放着「我的发布」和「外部样本」。"
        }
        action={<Button icon={<ReloadOutlined />} onClick={() => void loadNotes()} loading={isLoading}>刷新</Button>}
      />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title={fixedSource === "own" ? "笔记总数" : fixedSource === "library" ? "样本总数" : "已保存笔记"} value={total} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="当前视图" value={viewMode === "card" ? "卡片" : "表格"} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="已选择" value={selectedNoteIds.length} suffix="条" /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="平台" value="XHS" /></Card></Col>
      </Row>

      {filterNote ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={filterNote}
        />
      ) : null}

      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={12} align="middle">
          <Col span={5}><Input placeholder="标题、正文、作者" value={keywordFilter} onChange={(e) => setKeywordFilter(e.target.value)} allowClear /></Col>
          <Col span={4}><Select value={selectedTagFilter || undefined} onChange={(v) => setSelectedTagFilter(v ?? "")} placeholder="全部标签" allowClear style={{ width: "100%" }} options={availableTags.map((t) => ({ value: String(t.id), label: t.name }))} /></Col>
          <Col><Button size="small" onClick={() => setTagManagerOpen(true)}>管理标签</Button></Col>
          <Col><Checkbox checked={hasAssetsFilter} onChange={(e) => setHasAssetsFilter(e.target.checked)}>有素材</Checkbox></Col>
          <Col><Checkbox checked={hasCommentsFilter} onChange={(e) => setHasCommentsFilter(e.target.checked)}>有评论</Checkbox></Col>
          <Col span={3}>
            <Select
              allowClear
              value={contentFilter || undefined}
              onChange={(value) => setContentFilter((value as "ready" | "empty") ?? "")}
              placeholder="正文状态"
              style={{ width: "100%" }}
              options={[
                { value: "ready", label: "有正文（可蒸馏）" },
                { value: "empty", label: "缺正文" },
              ]}
            />
          </Col>
          <Col span={3}>
            {fixedSource ? (
              <Tag color={fixedSource === "own" ? "green" : "blue"} style={{ marginInlineEnd: 0 }}>
                {fixedSource === "own" ? "只看我的发布" : "只看外部样本"}
              </Tag>
            ) : (
              <Select
                value={sourceFilter}
                onChange={(value) => setSourceFilter(value as "all" | "own" | "library")}
                style={{ width: "100%" }}
                options={[
                  { value: "all", label: "全部来源" },
                  { value: "own", label: "我的发布" },
                  { value: "library", label: "外部样本" },
                ]}
              />
            )}
          </Col>
          <Col><Segmented value={viewMode} onChange={(v) => setViewMode(v as string)} options={[{ label: "卡片", value: "card" }, { label: "表格", value: "table" }]} /></Col>
          <Col><Button onClick={clearFilters}>重置</Button></Col>
          <Col><Button type="primary" onClick={() => { setPage(1); void loadNotes(undefined, 1, pageSize); }} loading={isLoading}>筛选</Button></Col>
        </Row>
        {fixedSource !== "own" ? (
          <Row gutter={12} align="middle" style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
            <Col><Text type="secondary" style={{ fontSize: 12 }}><FireOutlined style={{ color: token.colorWarning }} /> 低粉高赞</Text></Col>
            <Col span={3}><InputNumber min={0} step={1000} placeholder="粉丝上限" value={maxFansFilter} onChange={setMaxFansFilter} style={{ width: "100%" }} /></Col>
            <Col span={3}><InputNumber min={0} step={100} placeholder="点赞下限" value={minLikesFilter} onChange={setMinLikesFilter} style={{ width: "100%" }} /></Col>
            <Col span={3}><InputNumber min={0} step={0.1} precision={2} placeholder="赞粉比下限" value={minRatioFilter} onChange={setMinRatioFilter} style={{ width: "100%" }} /></Col>
            <Col span={4}><Select value={sortBy} onChange={setSortBy} style={{ width: "100%" }} options={[
              { value: "created_at", label: "按保存时间" },
              { value: "likes", label: "按点赞数" },
              { value: "like_fan_ratio", label: "按赞粉比" },
              { value: "engagement_rate", label: "按互动率" },
            ]} /></Col>
          </Row>
        ) : null}
      </Card>

      {notes.length > 0 && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Checkbox checked={notes.length > 0 && notes.every((n) => selectedNoteIdSet.has(n.id))} onChange={toggleVisibleSelection}>选择当前页</Checkbox>
            <Text strong>{selectedNoteIds.length} 条已选</Text>
            <Button type="primary" icon={<CheckSquareOutlined />} disabled={isBatchWorking || !selectedNoteIds.length} onClick={createBatchRewriteDrafts} size="small">批量加入草稿工坊</Button>
            <Button icon={<RobotOutlined />} disabled={isBatchWorking || !selectedNoteIds.length || selectedNoteIds.length > 5} onClick={() => void openBatchRewrite()} size="small">批量 AI 改写</Button>
            <Select
              size="small"
              value={batchTagId || undefined}
              onChange={(value) => setBatchTagId(value ?? "")}
              placeholder="选择标签"
              style={{ width: 140 }}
              options={availableTags.map((tag) => ({ value: String(tag.id), label: tag.name }))}
              disabled={isBatchWorking || !selectedNoteIds.length || !availableTags.length}
            />
            <Button size="small" disabled={isBatchWorking || !selectedNoteIds.length || !batchTagId} onClick={() => void applyBatchTag("add")}>
              加标签
            </Button>
            <Button size="small" disabled={isBatchWorking || !selectedNoteIds.length || !batchTagId} onClick={() => void applyBatchTag("remove")}>
              移除标签
            </Button>
            <Dropdown
              menu={{ items: batchMenuItems, onClick: ({ key }) => handleBatchMenu(key) }}
              trigger={["click"]}
              disabled={isBatchWorking || !selectedNoteIds.length}
            >
              <Button icon={<EllipsisOutlined />} disabled={isBatchWorking || !selectedNoteIds.length} size="small">
                更多操作 <DownOutlined />
              </Button>
            </Dropdown>
            <Button disabled={!selectedNoteIds.length} onClick={clearSelection} size="small">清空选择</Button>
          </Space>
            {backfillProgress.status !== "idle" && backfillProgress.total > 0 ? (
            <Card size="small" style={{ marginTop: 8 }}>
              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                <Space wrap size={8}>
                  <Text strong>补全正文</Text>
                  <Tag color={
                    backfillProgress.status === "cooling"
                      ? "orange"
                      : backfillProgress.status === "paused"
                        ? "default"
                        : "blue"
                  }>
                    {backfillProgress.status === "cooling"
                      ? "冷却中"
                      : backfillProgress.status === "paused"
                        ? "已停止"
                        : "进行中"}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    成功 {backfillProgress.filled} / 共 {backfillProgress.total} 篇
                  </Text>
                  {backfillProgress.status !== "paused" ? (
                    <Button
                      size="small"
                      danger
                      onClick={() => {
                        backfillCancelRef.current = true;
                      }}
                    >
                      停止
                    </Button>
                  ) : null}
                </Space>
                <Progress
                  percent={Math.round((backfillProgress.done / backfillProgress.total) * 100)}
                  size="small"
                  status={backfillProgress.status === "cooling" ? "exception" : "active"}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {backfillProgress.message}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  每篇间隔约 10 秒，连续被限流时自动冷却。中途停止不会丢已完成的进度。
                </Text>
              </Space>
            </Card>
          ) : null}
          {backfillFailures.length ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 8 }}
              message={`${backfillFailures.length} 篇补全失败`}
              description={
                <div style={{ fontSize: 12, maxHeight: 140, overflowY: "auto" }}>
                  {backfillFailures.slice(0, 10).map((item, index) => (
                    <div key={`${item.title}-${index}`}>
                      · {item.title}：{item.reason}
                    </div>
                  ))}
                  {backfillFailures.length > 10 ? (
                    <div>…另有 {backfillFailures.length - 10} 篇</div>
                  ) : null}
                  <div style={{ marginTop: 6, opacity: 0.75 }}>
                    多为 token 过期或笔记已删除。可选中后「标记正文不可用」，避免重复尝试。
                  </div>
                </div>
              }
              closable
              onClose={() => setBackfillFailures([])}
            />
          ) : null}
        </Card>
      )}

      {error && <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} />}

      {isLoading ? <Spin size="large" style={{ display: "block", textAlign: "center", margin: "48px 0" }} /> : visibleNotes.length === 0 ? (
        <Empty
          description={
            hasActiveFilters
              ? "没有符合当前筛选的笔记"
              : sourceFilter === "own"
                ? "还没有自己的发布笔记"
                : sourceFilter === "library"
                  ? "样本库还是空的"
                  : "笔记库还是空的"
          }
        >
          {hasActiveFilters ? (
            <Button onClick={clearFilters}>清除筛选</Button>
          ) : sourceFilter === "own" ? (
            <Link to="/settings/accounts"><Button type="primary" icon={<BookOutlined />}>去账号导入发布笔记</Button></Link>
          ) : (
            <Link to="/platforms/xhs/assets/collect"><Button type="primary" icon={<BookOutlined />}>去搜索样本</Button></Link>
          )}
        </Empty>
      ) : viewMode === "table" ? (
        <Card size="small">
          <Table<SavedNote> columns={tableColumns} dataSource={visibleNotes} rowKey="id" size="small" pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ["20", "50", "100"],
            showTotal: (value) => `共 ${value} 条`,
            onChange: (nextPage, nextSize) => {
              setPage(nextPage);
              setPageSize(nextSize);
              void loadNotes(undefined, nextPage, nextSize);
            },
          }} scroll={{ x: fixedSource === "own" ? 1050 : 1100 }}
            rowSelection={{ selectedRowKeys: selectedNoteIds, onChange: (keys) => setSelectedNoteIds(keys as number[]) }}
            onRow={(n) => ({ onClick: () => void openDetail(n), style: { cursor: "pointer" } })} />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {visibleNotes.map((note) => {
            const cover = getSavedNoteCoverUrl(note);
            const kind = getRawNoteType(note);
            return (
              <Col xs={12} sm={8} md={6} lg={4} xl={4} key={note.id}>
                <Card hoverable size="small" style={{ overflow: "hidden" }} onClick={() => void openDetail(note)}
                  cover={
                    <div style={{ position: "relative", background: token.colorFillQuaternary }}>
                      <Checkbox checked={selectedNoteIdSet.has(note.id)} onClick={(e) => { e.stopPropagation(); toggleNoteSelection(note.id); }} style={{ position: "absolute", top: 8, left: 8, zIndex: 2 }} />
                      {cover ? <img src={cover} alt={note.title} referrerPolicy="no-referrer" onError={(event) => { event.currentTarget.style.visibility = "hidden"; }} style={{ width: "100%", aspectRatio: "1/1", objectFit: "cover", display: "block" }} /> : <div style={{ width: "100%", aspectRatio: "1/1", display: "flex", alignItems: "center", justifyContent: "center", color: token.colorTextQuaternary, fontSize: 28 }}><PictureOutlined /></div>}
                      <Tag color={kind.includes("video") ? "purple" : "blue"} style={{ position: "absolute", top: 8, right: 8 }} icon={kind.includes("video") ? <PlayCircleOutlined /> : <PictureOutlined />}>{kind.includes("video") ? "视频" : "图文"}</Tag>
                    </div>
                  }>
                  <Card.Meta title={<Text ellipsis style={{ fontSize: 13 }}>{note.title || "未命名"}</Text>} description={
                    <>
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>{note.author_name}</Text>
                        {getNotePublishTime(note) ? <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>{getNotePublishTime(note)}</Text> : <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>{formatSavedTime(note.created_at)}</Text>}
                      </div>
                      {(() => {
                        const eng = getNoteEngagement(note);
                        if (!eng.likes && !eng.collects && !eng.comments && !eng.shares) return null;
                        return (
                          <div style={{ marginTop: 4, display: "flex", gap: 8, fontSize: 11, color: token.colorTextTertiary }}>
                            {eng.likes > 0 && <span><HeartOutlined /> {eng.likes}</span>}
                            {eng.collects > 0 && <span><StarOutlined /> {eng.collects}</span>}
                            {eng.comments > 0 && <span><MessageOutlined /> {eng.comments}</span>}
                            {eng.shares > 0 && <span><ShareAltOutlined /> {eng.shares}</span>}
                          </div>
                        );
                      })()}
                      {(note.author_fans || note.like_fan_ratio) ? (
                        <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 8 }}>
                          <Text type="secondary" style={{ fontSize: 11 }}>粉丝 {(note.author_fans ?? 0).toLocaleString()}</Text>
                          <Tag color={(note.like_fan_ratio ?? 0) >= 1 ? "gold" : "default"} style={{ fontSize: 10, marginInlineEnd: 0 }}>
                            赞粉比 {(note.like_fan_ratio ?? 0).toFixed(2)}
                          </Tag>
                        </div>
                      ) : null}
                    </>
                  } />
                  {note.tags?.length ? <div style={{ marginTop: 6 }}>{note.tags.map((t) => <Tag key={t.id} color="blue" style={{ fontSize: 11 }}>{t.name}</Tag>)}</div> : null}
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      {viewMode === "card" && total > 0 ? (
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            showSizeChanger
            pageSizeOptions={["20", "50", "100"]}
            showTotal={(value) => `共 ${value} 条`}
            onChange={(nextPage, nextSize) => {
              setPage(nextPage);
              setPageSize(nextSize);
              void loadNotes(undefined, nextPage, nextSize);
            }}
          />
        </div>
      ) : null}

      <Drawer title={selectedNote?.title || "笔记详情"} open={isDetailOpen} onClose={closeDetail} width={640} styles={{ body: { background: token.colorBgElevated } }}>
        {selectedNote && (
          <Spin spinning={isDetailLoading}>
            {detailError && <Alert message={detailError} type="warning" showIcon style={{ marginBottom: 12 }} />}
    
            <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="作者">{getAuthorProfileUrl(selectedNote) ? <Typography.Link href={getAuthorProfileUrl(selectedNote)} target="_blank" rel="noreferrer">{selectedNote.author_name || "未知"}</Typography.Link> : (selectedNote.author_name || "未知")}</Descriptions.Item>
              <Descriptions.Item label="互动">赞 {getNoteEngagement(selectedNote).likes} · 藏 {getNoteEngagement(selectedNote).collects} · 评 {getNoteEngagement(selectedNote).comments}</Descriptions.Item>
              <Descriptions.Item label="笔记 ID">{selectedNote.note_id}</Descriptions.Item>
              <Descriptions.Item label="保存时间">{formatSavedTime(selectedNote.created_at)}</Descriptions.Item>
              {getNotePublishTime(selectedNote) && <Descriptions.Item label="发布时间">{getNotePublishTime(selectedNote)}</Descriptions.Item>}
              <Descriptions.Item label="作品链接"><Typography.Link href={getNoteUrl(selectedNote)} target="_blank" rel="noreferrer" style={{ fontSize: 12, wordBreak: "break-all" }}>{getNoteUrl(selectedNote)}</Typography.Link></Descriptions.Item>
            </Descriptions>

            {getNoteTags(selectedNote).length > 0 && (
              <div style={{ marginBottom: 12 }}>{getNoteTags(selectedNote).map((t) => <Tag key={t} color="blue">#{t}</Tag>)}</div>
            )}

            <Card size="small" style={{ marginBottom: 16 }}>
              <Text strong style={{ display: "block", marginBottom: 8 }}>标签</Text>
              <Space wrap size={[6, 6]}>
                {availableTags.map((tag) => (
                  <Tag.CheckableTag
                    key={tag.id}
                    checked={selectedNoteHasTag(tag.id)}
                    onChange={() => void toggleSelectedTag(tag)}
                  >
                    {tag.name}
                  </Tag.CheckableTag>
                ))}
              </Space>
              <Space.Compact style={{ marginTop: 8, width: "100%" }}>
                <Input
                  size="small"
                  value={newTagName}
                  onChange={(event) => setNewTagName(event.target.value)}
                  placeholder="新标签名"
                  onPressEnter={() => void createAndAssignTag()}
                />
                <Button size="small" onClick={() => void createAndAssignTag()}>
                  新建并添加
                </Button>
              </Space.Compact>
            </Card>

            <Button type="link" icon={<LinkOutlined />} href={getNoteUrl(selectedNote)} target="_blank" rel="noreferrer" style={{ padding: 0, marginBottom: 16 }}>查看原文</Button>

            <Space wrap style={{ marginBottom: 16 }}>
              <Button icon={<CopyOutlined />} onClick={copySelectedNote} size="small">复制内容</Button>
              <Button icon={<FileAddOutlined />} onClick={addToDrafts} loading={isCreatingDraft} size="small">加入草稿工坊</Button>
              <Button icon={<EditOutlined />} onClick={() => createDraft("rewrite")} loading={isCreatingDraft} size="small">AI 改写</Button>
              {fixedSource === "own" ? (
                <Link
                  to={`/platforms/xhs/dashboard/review?account_id=${selectedNote.platform_account_id ?? ""}&note_id=${encodeURIComponent(selectedNote.note_id)}`}
                  onClick={() => setSelectedNote(null)}
                >
                  <Button icon={<LineChartOutlined />} size="small">看复盘</Button>
                </Link>
              ) : null}
              <Popconfirm title="确定删除？" onConfirm={() => void handleDeleteNote(selectedNote)}><Button danger icon={<DeleteOutlined />} size="small">删除</Button></Popconfirm>
            </Space>

            <Card size="small" style={{ marginBottom: 16, background: token.colorFillQuaternary }}>
              <Text strong style={{ display: "block", marginBottom: 8 }}>内容诊断</Text>
              <ViralAnalysisPanel
                noteDbId={selectedNote.id}
                noteTitle={selectedNote.title}
                accountId={selectedNote.platform_account_id}
              />
            </Card>

            {selectedAssets.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Space style={{ marginBottom: 6 }}>
                  <Text strong>素材 ({selectedAssets.length})</Text>
                  <Button size="small" onClick={() => setAssetManagerOpen(true)}>
                    管理素材
                  </Button>
                </Space>
                <Image.PreviewGroup>
                  <Space size={8} wrap>
                    {selectedAssets.map((a) => (
                      a.asset_type === "video" ? (
                        <div key={a.id} style={{ width: 80, height: 80, background: token.colorFillQuaternary, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <Button type="link" icon={<PlayCircleOutlined />} href={a.url} target="_blank" rel="noreferrer">视频</Button>
                        </div>
                      ) : <Image key={a.id} src={a.url} width={80} height={80} style={{ objectFit: "cover", borderRadius: 8 }} referrerPolicy="no-referrer" />
                    ))}
                  </Space>
                </Image.PreviewGroup>
              </div>
            )}

            <div style={{ marginBottom: 16 }}>
              <Text strong>正文</Text>
              <Paragraph style={{ marginTop: 4, color: token.colorTextSecondary, whiteSpace: "pre-wrap" }}>{selectedNote.content || "暂无正文。"}</Paragraph>
            </div>

            <Button onClick={toggleComments} style={{ marginBottom: 8 }}>{isCommentsOpen ? "收起评论" : `查看评论 (${commentsTotal})`}</Button>
            <Button
              icon={<MessageOutlined />}
              loading={isFetchingComments}
              onClick={() => void fetchNoteComments()}
              style={{ marginLeft: 8, marginBottom: 8 }}
            >
              抓取评论
            </Button>
            <Button icon={<ReloadOutlined />} loading={isSyncing} onClick={() => void syncNoteMetrics()} style={{ marginLeft: 8, marginBottom: 8 }}>
              同步最新数据
            </Button>
            {isCommentsOpen && (
              <Card size="small" style={{ background: token.colorFillQuaternary }}>
                {commentsError && <Alert message={commentsError} type="error" showIcon style={{ marginBottom: 8 }} />}
                {isCommentsLoading && <Spin size="small" />}
                {topLevelComments.length === 0 && !isCommentsLoading ? <Text type="secondary">暂无评论</Text> : null}
                {topLevelComments.map((c) => (
                  <div key={c.comment_id} style={{ marginBottom: 10, paddingBottom: 8, borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
                    <Space><Text strong style={{ fontSize: 13 }}>{c.user_name}</Text><Text type="secondary" style={{ fontSize: 11 }}>{c.created_at_remote} · {c.like_count} likes</Text></Space>
                    <div style={{ color: token.colorTextSecondary, fontSize: 13, marginTop: 2 }}>{c.content}</div>
                    {childComments(c.comment_id).map((r) => (
                      <div key={r.comment_id} style={{ marginLeft: 20, marginTop: 4, paddingLeft: 8, borderLeft: `2px solid ${token.colorBorderSecondary}` }}>
                        <Space><Text strong style={{ fontSize: 12 }}>{r.user_name}</Text><Text type="secondary" style={{ fontSize: 11 }}>{r.like_count} likes</Text></Space>
                        <div style={{ color: token.colorTextTertiary, fontSize: 12 }}>{r.content}</div>
                      </div>
                    ))}
                  </div>
                ))}
                {comments.length < commentsTotal && <Button size="small" onClick={() => void loadComments(commentsPage + 1)} loading={isCommentsLoading}>加载更多</Button>}
              </Card>
            )}

            {selectedNote.raw_json && (
              <details style={{ marginTop: 16 }}>
                <summary style={{ cursor: "pointer", color: token.colorTextTertiary, fontSize: 12 }}>原始 JSON</summary>
                <pre style={{ fontSize: 11, color: token.colorTextSecondary, background: token.colorFillQuaternary, padding: 8, borderRadius: 8, overflow: "auto", maxHeight: 300 }}>{JSON.stringify(selectedNote.raw_json, null, 2)}</pre>
              </details>
            )}
          </Spin>
        )}
      </Drawer>

      <Modal
        open={rewriteOpen}
        title="批量 AI 改写"
        onCancel={() => setRewriteOpen(false)}
        width={720}
        footer={
          <Space>
            <Button onClick={() => setRewriteOpen(false)}>关闭</Button>
            <Button type="primary" icon={<RobotOutlined />} loading={rewriteBusy} onClick={() => void submitBatchRewrite()}>
              生成改写草稿
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="只生成草稿，不复制原图，不自动发布"
            description="会结合账号的创作 Skill 和去 AI 味 Skill 改写；生成后请到草稿工坊人工检查。"
          />
          <Row gutter={8}>
            <Col span={12}>
              <Text type="secondary" style={{ fontSize: 12 }}>目标账号</Text>
              <Select
                allowClear
                value={rewriteAccountId ?? undefined}
                onChange={(value) => setRewriteAccountId(value ?? null)}
                placeholder="不选则使用通用规则"
                style={{ width: "100%" }}
                options={rewriteAccounts.map((account) => ({
                  value: account.id,
                  label: account.nickname || `账号 ${account.id}`,
                }))}
              />
            </Col>
            <Col span={12}>
              <Text type="secondary" style={{ fontSize: 12 }}>已选笔记</Text>
              <div style={{ paddingTop: 6 }}><Tag color="blue">{selectedNoteIds.length} 条</Tag></div>
            </Col>
          </Row>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>补充要求（可选）</Text>
            <Input.TextArea
              rows={3}
              value={rewriteInstruction}
              onChange={(event) => setRewriteInstruction(event.target.value)}
              placeholder="例如：保留主题，但换成一人公司视角；不要复制原句。"
            />
          </div>
          {rewriteResult ? (
            <div>
              <Text strong style={{ fontSize: 12 }}>生成结果</Text>
              <List
                size="small"
                dataSource={rewriteResult.items}
                renderItem={(item) => (
                  <List.Item
                    actions={
                      item.draft
                        ? [
                            <Button
                              key="adopt"
                              type={rewriteAdopted.includes(item.draft.id) ? "primary" : "link"}
                              size="small"
                              onClick={() => toggleRewriteAdopt(item.draft!.id)}
                            >
                              {rewriteAdopted.includes(item.draft.id) ? "已采用" : "采用"}
                            </Button>,
                            <Button
                              key="rewrite"
                              type="link"
                              size="small"
                              loading={rewriteBusyDraftId === item.draft.id}
                              onClick={() => void rewriteResultDraft(item.draft!.id)}
                            >
                              重写
                            </Button>,
                            <Popconfirm
                              key="discard"
                              title="废弃这个改写草稿？"
                              okText="废弃"
                              cancelText="取消"
                              okButtonProps={{ danger: true }}
                              onConfirm={() => void discardRewriteDraft(item.draft!.id)}
                            >
                              <Button type="link" size="small" danger loading={rewriteBusyDraftId === item.draft.id}>
                                废弃
                              </Button>
                            </Popconfirm>,
                          ]
                        : []
                    }
                  >
                    <List.Item.Meta
                      title={
                        <Space wrap>
                          <Text style={{ fontSize: 12 }}>
                            笔记 #{item.source_note_id}
                            {item.draft ? ` → 草稿 #${item.draft.id}：${item.draft.title}` : " 失败"}
                          </Text>
                          {item.draft && rewriteAdopted.includes(item.draft.id) ? <Tag color="blue">已采用</Tag> : null}
                        </Space>
                      }
                      description={
                        <Space wrap size={4}>
                          {item.similarity !== undefined ? <Tag color={item.similarity >= 0.8 ? "orange" : "green"}>相似度 {item.similarity}</Tag> : null}
                          {item.preflight ? (
                            <Tag color={item.preflight.ok ? (item.preflight.warning_count ? "orange" : "green") : "red"}>
                              {String(item.preflight?.summary ?? "")}
                            </Tag>
                          ) : null}
                          {item.warning ? <Text type="warning" style={{ fontSize: 11 }}>{item.warning}</Text> : null}
                          {(item.preflight?.errors ?? []).map((check: { key?: string; message?: string }) => (
                            <Text key={check.key ?? check.message} type="danger" style={{ fontSize: 11 }}>{check.message}</Text>
                          ))}
                          {item.error ? <Text type="danger" style={{ fontSize: 11 }}>{item.error}</Text> : null}
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
              {rewriteAdopted.length ? (
                <Button
                  type="primary"
                  style={{ marginTop: 12 }}
                  onClick={() =>
                    navigate(`/platforms/xhs/publish-hub/calendar?draft_ids=${rewriteAdopted.join(",")}`)
                  }
                >
                  去排期已采用（{rewriteAdopted.length}）
                </Button>
              ) : null}
            </div>
          ) : null}
        </Space>
      </Modal>

      <Modal
        title="管理素材"
        open={assetManagerOpen}
        footer={null}
        onCancel={() => setAssetManagerOpen(false)}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space.Compact style={{ width: "100%" }}>
            <Input
              value={newAssetUrl}
              onChange={(event) => setNewAssetUrl(event.target.value)}
              placeholder="粘贴图片链接"
              onPressEnter={() => void addAssetFromUrl()}
            />
            <Button
              type="primary"
              loading={assetBusyId === -1}
              onClick={() => void addAssetFromUrl()}
            >
              添加
            </Button>
          </Space.Compact>
          {selectedAssets.length === 0 ? (
            <Empty description="还没有素材" />
          ) : (
            <List
              dataSource={selectedAssets}
              renderItem={(asset) => (
                <List.Item
                  actions={[
                    <Button
                      key="up"
                      size="small"
                      type="link"
                      onClick={() => void moveAsset(asset, -1)}
                    >
                      上移
                    </Button>,
                    <Button
                      key="down"
                      size="small"
                      type="link"
                      onClick={() => void moveAsset(asset, 1)}
                    >
                      下移
                    </Button>,
                    <Popconfirm
                      key="delete"
                      title="删除这个素材？"
                      onConfirm={() => void removeSelectedAsset(asset)}
                    >
                      <Button
                        size="small"
                        type="link"
                        danger
                        loading={assetBusyId === asset.id}
                      >
                        删除
                      </Button>
                    </Popconfirm>,
                  ]}
                >
                  <Space>
                    {asset.asset_type === "image" ? (
                      <Image
                        src={asset.url}
                        width={56}
                        height={56}
                        style={{ objectFit: "cover", borderRadius: 8 }}
                        referrerPolicy="no-referrer"
                      />
                    ) : null}
                    <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: asset.url }}>
                      {asset.url}
                    </Text>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Space>
      </Modal>

      <Modal
        title="标签管理"
        open={tagManagerOpen}
        footer={null}
        onCancel={() => {
          setTagManagerOpen(false);
          setTagEditId(null);
          setTagEditName("");
        }}
      >
        {availableTags.length === 0 ? (
          <Empty description="还没有标签" />
        ) : (
          <List
            dataSource={availableTags}
            renderItem={(tag) => (
              <List.Item
                actions={[
                  tagEditId === tag.id ? (
                    <Button
                      key="save"
                      size="small"
                      type="primary"
                      loading={tagBusyId === tag.id}
                      onClick={() => void saveTagName(tag)}
                    >
                      保存
                    </Button>
                  ) : (
                    <Button
                      key="edit"
                      size="small"
                      type="link"
                      onClick={() => startEditTag(tag)}
                    >
                      重命名
                    </Button>
                  ),
                  <Popconfirm
                    key="delete"
                    title={`删除标签「${tag.name}」？`}
                    description="会同时移除笔记上的这个标签，笔记本身不受影响。"
                    onConfirm={() => void removeTag(tag)}
                  >
                    <Button size="small" type="link" danger loading={tagBusyId === tag.id}>
                      删除
                    </Button>
                  </Popconfirm>,
                ]}
              >
                {tagEditId === tag.id ? (
                  <Input
                    value={tagEditName}
                    onChange={(event) => setTagEditName(event.target.value)}
                    onPressEnter={() => void saveTagName(tag)}
                    style={{ width: 260 }}
                    maxLength={32}
                  />
                ) : (
                  <Tag color={tag.color || undefined}>{tag.name}</Tag>
                )}
              </List.Item>
            )}
          />
        )}
      </Modal>

      <NextStepBar
        description="素材选好后，下一步通常是选题或写稿；已经写完的笔记可以直接进发布中心。"
        actions={[
          { label: "去选题库", to: "/platforms/xhs/plan" },
          { label: "去草稿工坊", to: "/platforms/xhs/write/drafts", primary: true },
        ]}
      />
    </div>
  );
}
