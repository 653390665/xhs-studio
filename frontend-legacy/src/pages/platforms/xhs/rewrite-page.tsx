import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileImageOutlined,
  HeartOutlined,
  HighlightOutlined,
  InboxOutlined,
  LinkOutlined,
  MessageOutlined,
  PictureOutlined,
  PlayCircleOutlined,
  PlusCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
  StarOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import { DndContext, closestCenter, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { SortableContext, horizontalListSortingStrategy, arrayMove } from "@dnd-kit/sortable";
import {
  Alert,
  Avatar,
  Button,
  Card,
  Col,
  Divider,
  Drawer,
  Form,
  Image,
  Input,
  message as antMessage,
  Modal,
  Popconfirm,
  Popover,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
  Tag,
  theme,
  Typography,
  Upload,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import { AssistantChat } from "./rewrite/assistant-chat";
import { AssistantFooter } from "./rewrite/assistant-footer";
import { AssistantPatchCard } from "./rewrite/assistant-patch-card";
import { AssistantTools } from "./rewrite/assistant-tools";
import { AssistantVersionList } from "./rewrite/assistant-version-list";
import { DraftPreflightCard } from "./rewrite/draft-preflight-card";
import { DraftQueue, type DraftReadinessFilter, type DraftReviewFilter } from "./rewrite/draft-queue";
import { ScoreCard } from "./rewrite/score-card";
import { SortableRewriteImage } from "./rewrite/sortable-rewrite-image";
import { TemplatePreview } from "./rewrite/template-preview";
import {
  type VisualBriefExpert,
  addDraftAsset,
  applyDraftChat,
  buildDraftVisualBrief,
  checkStructure,
  checkXhsSensitiveWords,
  deleteDraft,
  deleteDraftAsset,
  draftChat,
  fetchAccounts,
  fetchCurrentCreationSkill,
  fetchDraftAssets,
  fetchDraftChat,
  fetchDraftPreflight,
  fetchDraftVersions,
  fetchDrafts,
  fetchGeneratedImageAssets,
  fetchSavedNote,
  fetchUserImages,
  fetchViralTemplates,
  fetchXhsRedfoxStatus,
  scoreDraftWithSkill,
  scoreXhsNote,
  scoreXhsTitle,
  generateImageWithAi,
  generateFromImages,
  generateNoteWithAi,
  generateTagOptions,
  generateTitleOptions,
  recommendXhsTopics,
  reorderDraftAssets,
  restoreDraftVersion,
  reviewDraft,
  rewriteDraftWithAi,
  sendDraftToPublish,
  updateDraft,
  updateDraftAsset,
  uploadAssetFile,
} from "../../../lib/api";
import type { DraftAsset, DraftChatResponse, DraftVersionRecord, NoteScoreResult, PublishPreflight, SkillScoreResult, StructureCheckResult, TitleScoreResult, VisualBrief, XhsTopicRecommendation } from "../../../lib/api";
import type { Draft, CreationSkill, GeneratedImageAsset, PlatformAccount, SavedNote, UserImageFile, ViralTemplate, XhsRedfoxStatus, XhsSensitiveWordResult } from "../../../types";

const { Text, Paragraph, Title } = Typography;
const { TextArea } = Input;

const STRUCTURE_POSITION_LABELS: Record<string, string> = {
  opening: "开头",
  body: "中段",
  closing: "结尾",
};
type AiContentMode = "rewrite" | "generate";
const CHAT_WELCOME = "我是这篇草稿的创作搭档。你可以让我按 Skill 检查、改标题、补数字、缩正文或换 CTA；我会先给建议，你确认后再应用。";

function imageAssetUrl(asset: DraftAsset): string {
  return asset.url || (asset.local_path ? `/api/files/media/${asset.local_path}` : "");
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

const segmentedOptions = [
  {
    value: "rewrite" as const,
    label: "改写已有草稿",
    icon: <EditOutlined />,
  },
  {
    value: "generate" as const,
    label: "生成新草稿",
    icon: <PlusCircleOutlined />,
  },
];

/* ── helpers ───────────────────────────────────────────────────────── */

function isValidUrl(s: string): boolean {
  return s.startsWith("http://") || s.startsWith("https://");
}

function getAssetTypeFromUrl(url: string): "image" | "video" {
  const lower = url.toLowerCase();
  if (/\.(mp4|mov|avi|mkv|flv|wmv)/.test(lower)) return "video";
  return "image";
}

export function XhsDraftsPage() {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const [activeMode, setActiveMode] = useState<AiContentMode>("rewrite");
  const [batchOpen, setBatchOpen] = useState(false);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [reviewFilter, setReviewFilter] = useState<DraftReviewFilter>("all");
  const [readinessFilter, setReadinessFilter] = useState<DraftReadinessFilter>("all");
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [originFilter, setOriginFilter] = useState<string>("all");
  const editorSnapshot = useRef<string>("");
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [searchParams] = useSearchParams();
  const initialDraftId = useMemo(() => {
    const raw = searchParams.get("draft_id");
    const value = Number(raw);
    return raw && Number.isFinite(value) && value > 0 ? value : null;
  }, [searchParams]);
  const publishIntent = searchParams.get("intent") === "publish";
  const lastDraftQueryRef = useRef<number | null>(null);

  useEffect(() => {
    const value = searchParams.get("readiness");
    if (value === "ready" || value === "missing_media" || value === "missing_account") {
      setReadinessFilter(value);
    } else {
      setReadinessFilter("all");
    }
  }, [searchParams]);
  const [queueVisible, setQueueVisible] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [draftAccountId, setDraftAccountId] = useState<number | null>(null);
  const [imageWriterOpen, setImageWriterOpen] = useState(false);
  const [writerFiles, setWriterFiles] = useState<File[]>([]);
  const [writerPreviews, setWriterPreviews] = useState<string[]>([]);
  const [writerHint, setWriterHint] = useState("");
  const [writerGenerating, setWriterGenerating] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [instruction, setInstruction] = useState("保留事实，增强小红书种草感，语气自然。");
  const [topic, setTopic] = useState("");
  const [reference, setReference] = useState("");
  const [titleOptions, setTitleOptions] = useState<string[]>([]);
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [systemPrompt, setSystemPrompt] = useState(
    "口语化第一人称，保留事实和数据，不编造效果；标题不超过 20 字，正文 300–800 字，结尾留一个具体问题。",
  );
  const [sourceNote, setSourceNote] = useState<SavedNote | null>(null);
  const [sourceAssets, setSourceAssets] = useState<DraftAsset[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isRewriting, setIsRewriting] = useState(false);
  const [isPolishingTitles, setIsPolishingTitles] = useState(false);
  const [isPolishingTags, setIsPolishingTags] = useState(false);
  const [isCheckingWords, setIsCheckingWords] = useState(false);
  const [wordCheck, setWordCheck] = useState<XhsSensitiveWordResult | null>(null);
  const [topicRecs, setTopicRecs] = useState<XhsTopicRecommendation[]>([]);
  const [isLoadingTopics, setIsLoadingTopics] = useState(false);
  const [templates, setTemplates] = useState<ViralTemplate[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [enhanceMiddle, setEnhanceMiddle] = useState(false);
  const [structureCheck, setStructureCheck] = useState<StructureCheckResult | null>(null);
  const [isCheckingStructure, setIsCheckingStructure] = useState(false);
  const [activeSkill, setActiveSkill] = useState<CreationSkill | null>(null);
  const [scoreResult, setScoreResult] = useState<TitleScoreResult | NoteScoreResult | null>(null);
  const [skillScore, setSkillScore] = useState<SkillScoreResult | null>(null);
  const [isScoringSkill, setIsScoringSkill] = useState(false);
  const [visualBriefOpen, setVisualBriefOpen] = useState(false);
  const [visualBrief, setVisualBrief] = useState<VisualBrief | null>(null);
  const [isBuildingVisualBrief, setIsBuildingVisualBrief] = useState(false);
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; content: string }>>([
    { role: "assistant", content: CHAT_WELCOME },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [isChatting, setIsChatting] = useState(false);
  const [chatPatch, setChatPatch] = useState<DraftChatResponse["patch"]>(null);
  const [chatChanges, setChatChanges] = useState<string[]>([]);
  const [chatScore, setChatScore] = useState<SkillScoreResult | null>(null);
  const [chatMessageId, setChatMessageId] = useState<number | null>(null);
  const [draftVersions, setDraftVersions] = useState<DraftVersionRecord[]>([]);
  const [isApplyingChat, setIsApplyingChat] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewScore, setPreviewScore] = useState<TitleScoreResult | NoteScoreResult | null>(null);
  const [scoringKind, setScoringKind] = useState<string | null>(null);
  const [redfoxStatus, setRedfoxStatus] = useState<XhsRedfoxStatus | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSendingPublish, setIsSendingPublish] = useState(false);
  const [sendError, setSendError] = useState("");
  const [draftPreflight, setDraftPreflight] = useState<PublishPreflight | null>(null);
  const [isPreflightLoading, setIsPreflightLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rewritePreview, setRewritePreview] = useState<{ title: string; body: string } | null>(null);
  const [rewriteOriginal, setRewriteOriginal] = useState<{ title: string; body: string } | null>(null);
  const [optimizeModalOpen, setOptimizeModalOpen] = useState(false);
  const [optimizeAssetId, setOptimizeAssetId] = useState<number | null>(null);
  const [optimizePrompt, setOptimizePrompt] = useState("");
  const [optimizeRefImages, setOptimizeRefImages] = useState<string[]>([]);
  const [optimizeResult, setOptimizeResult] = useState<string | null>(null);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [assetUrl, setAssetUrl] = useState("");
  const [draftTags, setDraftTags] = useState<{id: string; name: string}[]>([]);
  const [pillar, setPillar] = useState("");
  const [experiment, setExperiment] = useState("");
  const [newTagInput, setNewTagInput] = useState("");
  const [isAddingTag, setIsAddingTag] = useState(false);
  const [userImages, setUserImages] = useState<UserImageFile[]>([]);
  const [aiAssets, setAiAssets] = useState<GeneratedImageAsset[]>([]);
  const [selectedAssetUrls, setSelectedAssetUrls] = useState<string[]>([]);
  const [refPickerOpen, setRefPickerOpen] = useState(false);
  const [refPickerUrlInput, setRefPickerUrlInput] = useState("");

  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) ?? null;
  const selectedDraftTemplate = selectedDraft
    ? templates.find((item) => item.id === selectedDraft.template_id) ?? null
    : null;
  const canCheckStructure = selectedDraftTemplate?.payload?.kind === "positional";
  const activeTemplates = templates.filter((item) => item.is_active !== false);
  const imageAssets = sourceAssets.filter((a) => a.asset_type === "image");
  const hasImageAssets = imageAssets.length > 0;
  const hasVideoAssets = sourceAssets.some((a) => a.asset_type === "video");
  const accountBound = Boolean(draftAccountId ?? selectedDraft?.platform_account_id);
  const contentReady = Boolean(title.trim() && body.trim());
  const missingMediaCount = drafts.filter((draft) => draft.media_ready === false).length;
  const sendBlockReason = !selectedDraft
    ? "请先选择一个草稿。"
    : !accountBound
      ? "请先绑定发布账号。"
      : sourceAssets.length === 0
        ? "请先添加至少一张图片或视频。"
        : isPreflightLoading
          ? "正在检查发布条件，请稍候。"
          : !draftPreflight
            ? "发布检查尚未完成，请点「重新检查」。"
            : !draftPreflight.ok
              ? draftPreflight.summary
              : "";
  const canSendToPublish = sendBlockReason === "";

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setSourceAssets((prev) => {
      const images = prev.filter((a) => a.asset_type === "image");
      const others = prev.filter((a) => a.asset_type !== "image");
      const oldIdx = images.findIndex((a) => a.id === Number(active.id));
      const newIdx = images.findIndex((a) => a.id === Number(over.id));
      if (oldIdx < 0 || newIdx < 0) return prev;
      const reorderedImages = arrayMove(images, oldIdx, newIdx);
      const result = [...reorderedImages, ...others];
      const draftId = selectedDraft?.id;
      if (draftId) {
        const ids = reorderedImages.filter((a) => a.id > 0).map((a) => a.id);
        void reorderDraftAssets(draftId, ids).catch((err) => { console.error("reorder failed", err); });
      }
      return result;
    });
  }

  function handleRemoveAsset(assetId: number) {
    const draftId = selectedDraft?.id;
    const removed = sourceAssets.find((asset) => asset.id === assetId);
    setSourceAssets((prev) => prev.filter((a) => a.id !== assetId));
    if (draftId && assetId > 0) {
      void deleteDraftAsset(draftId, assetId).catch(() => {
        if (removed) {
          setSourceAssets((prev) => (
            prev.some((asset) => asset.id === removed.id) ? prev : [...prev, removed]
          ));
        }
        antMessage.error("删除素材失败，请重试。");
      });
    }
  }

  function handleWriterUpload(file: File): false {
    if (!file.type.startsWith("image/")) {
      antMessage.warning("只支持图片文件");
      return false;
    }
    setWriterFiles((prev) => [...prev, file].slice(0, 9));
    setWriterPreviews((prev) => [...prev, URL.createObjectURL(file)].slice(0, 9));
    return false;
  }

  function removeWriterImage(index: number) {
    setWriterFiles((prev) => prev.filter((_, i) => i !== index));
    setWriterPreviews((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleGenerateFromImages() {
    if (!writerFiles.length) {
      antMessage.warning("请先上传图片");
      return;
    }
    setWriterGenerating(true);
    clearStatus();
    try {
      const uploaded: Array<{ file_name: string; url: string }> = [];
      for (const file of writerFiles) {
        const result = await uploadAssetFile(file);
        uploaded.push({ file_name: result.file_name, url: result.download_url });
      }
      const draft = await generateFromImages({
        platform: "xhs",
        images: uploaded,
        instruction: writerHint.trim(),
        account_id: draftAccountId,
        template_id: templateId,
      });
      upsertDraft(draft as Draft, "generate");
      setImageWriterOpen(false);
      setWriterFiles([]);
      setWriterPreviews([]);
      setWriterHint("");
      antMessage.success(`已根据 ${uploaded.length} 张图生成草稿 #${draft.id}`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      antMessage.error(detail || "图片成稿失败，请确认图片/文本模型可用");
    } finally {
      setWriterGenerating(false);
    }
  }

  function handleFileUpload(file: File): false {
    const draftId = selectedDraft?.id;
    (async () => {
      try {
        const uploaded = await uploadAssetFile(file);
        if (draftId) {
          const saved = await addDraftAsset(draftId, {
            asset_type: uploaded.asset_type,
            url: uploaded.download_url,
            local_path: uploaded.file_name,
          });
          setSourceAssets((prev) => [...prev, saved]);
        } else {
          setSourceAssets((prev) => [...prev, {
            id: -(Date.now()),
            draft_id: 0,
            asset_type: uploaded.asset_type,
            url: uploaded.download_url,
            local_path: uploaded.file_name,
            sort_order: prev.length,
          }]);
        }
        antMessage.success("文件上传成功");
      } catch {
        antMessage.error("文件上传失败");
      }
    })();
    return false;
  }

  function handleUrlAdd() {
    const trimmed = assetUrl.trim();
    if (!trimmed) { antMessage.warning("请输入素材链接。"); return; }
    if (!isValidUrl(trimmed)) { antMessage.error("链接格式不正确，请输入 http:// 或 https:// 开头的链接。"); return; }
    const assetType = getAssetTypeFromUrl(trimmed);
    const draftId = selectedDraft?.id;
    if (draftId) {
      (async () => {
        try {
          const saved = await addDraftAsset(draftId, { asset_type: assetType, url: trimmed });
          setSourceAssets((prev) => [...prev, saved]);
          setAssetUrl("");
          setUploadModalOpen(false);
        } catch { antMessage.error("添加素材失败"); }
      })();
    } else {
      setSourceAssets((prev) => [...prev, {
        id: -(Date.now()),
        draft_id: 0,
        asset_type: assetType,
        url: trimmed,
        local_path: "",
        sort_order: prev.length,
      }]);
      setAssetUrl("");
      setUploadModalOpen(false);
    }
  }

  function toggleAssetUrl(url: string) {
    setSelectedAssetUrls(prev => prev.includes(url) ? prev.filter(u => u !== url) : [...prev, url]);
  }

  function handleAddSelectedAssets() {
    const draftId = selectedDraft?.id;
    (async () => {
      for (const url of selectedAssetUrls) {
        if (draftId) {
          try {
            const saved = await addDraftAsset(draftId, { asset_type: "image", url });
            setSourceAssets(prev => [...prev, saved]);
          } catch { /* ignore individual failures */ }
        } else {
          setSourceAssets(prev => [...prev, {
            id: -(Date.now() + Math.random()),
            draft_id: 0,
            asset_type: "image",
            url,
            local_path: "",
            sort_order: prev.length,
          }]);
        }
      }
      setSelectedAssetUrls([]);
      setUploadModalOpen(false);
      antMessage.success(`已添加 ${selectedAssetUrls.length} 个图片`);
    })();
  }

  function clearStatus() {
    setError(null);
  }

  async function loadDraftPreflight(draftId?: number, accountId?: number | null) {
    const targetId = draftId ?? selectedDraft?.id;
    if (!targetId) {
      setDraftPreflight(null);
      return;
    }
    setIsPreflightLoading(true);
    try {
      setDraftPreflight(await fetchDraftPreflight(targetId, accountId ?? draftAccountId));
    } catch {
      setDraftPreflight(null);
    } finally {
      setIsPreflightLoading(false);
    }
  }

  function draftSignature(draft: Draft | null): string {
    if (!draft) return "";
    return JSON.stringify({
      title: draft.title || "",
      body: draft.body || "",
      tags: (Array.isArray(draft.tags) ? draft.tags : []).map((tag) => tag.name || ""),
      account: draft.platform_account_id ?? null,
      pillar: draft.pillar || "",
      experiment: draft.experiment || "",
    });
  }

  function editorSignature(): string {
    return JSON.stringify({
      title,
      body,
      tags: draftTags.map((tag) => tag.name || ""),
      account: draftAccountId,
      pillar,
      experiment,
    });
  }

  function hasUnsavedChanges(): boolean {
    return Boolean(editorSnapshot.current) && editorSignature() !== editorSnapshot.current;
  }

  function confirmDiscard(onOk: () => void) {
    if (!hasUnsavedChanges()) {
      onOk();
      return;
    }
    Modal.confirm({
      title: "有未保存的修改",
      content: "切换后当前标题、正文或标签的修改会丢失。",
      okText: "放弃修改",
      cancelText: "继续编辑",
      okButtonProps: { danger: true },
      onOk,
    });
  }

  function selectDraft(draft: Draft, mode: AiContentMode = "rewrite", force = false) {
    if (!force && hasUnsavedChanges()) {
      Modal.confirm({
        title: "有未保存的修改",
        content: "切换草稿后当前修改会丢失，确定继续吗？",
        okText: "放弃修改并切换",
        cancelText: "继续编辑",
        okButtonProps: { danger: true },
        onOk: () => selectDraft(draft, mode, true),
      });
      return;
    }
    setActiveMode(mode);
    setSelectedDraftId(draft.id);
    setDraftAccountId(draft.platform_account_id ?? null);
    setTitle(draft.title);
    setBody(draft.body);
    setDraftTags(
      Array.isArray(draft.tags)
        ? draft.tags.map((t) => ({ id: t.id || "", name: t.name || "" }))
        : [],
    );
    setPillar(draft.pillar || "");
    setExperiment(draft.experiment || "");
    editorSnapshot.current = draftSignature(draft);
    setSendError("");
    clearStatus();
  }

  function goToDraftImages(draft: Draft) {
    const target = `/platforms/xhs/write/visual/images?draft_id=${draft.id}`;
    const go = () => {
      selectDraft(draft, activeMode, true);
      navigate(target);
    };
    if (!hasUnsavedChanges()) {
      go();
      return;
    }
    Modal.confirm({
      title: "有未保存的修改",
      content: "去配图前需要先离开当前编辑内容，未保存的修改会丢失。",
      okText: "放弃修改并去配图",
      cancelText: "继续编辑",
      okButtonProps: { danger: true },
      onOk: go,
    });
  }

  async function loadDrafts() {
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchDrafts("xhs", {
        review_status: reviewFilter,
        origin: originFilter,
        page_size: 100,
      });
      setDrafts(result.items);
      const current = selectedDraftId
        ? result.items.find((draft) => draft.id === selectedDraftId)
        : initialDraftId
          ? result.items.find((draft) => draft.id === initialDraftId) ?? result.items[0]
          : result.items[0];
      if (current) {
        setSelectedDraftId(current.id);
        setDraftAccountId(current.platform_account_id ?? null);
        setTitle(current.title);
        setBody(current.body);
        setDraftTags(
          Array.isArray(current.tags)
            ? current.tags.map((t) => ({ id: t.id || "", name: t.name || "" }))
            : [],
        );
        setPillar(current.pillar || "");
        setExperiment(current.experiment || "");
        editorSnapshot.current = draftSignature(current);
      } else {
        setSelectedDraftId(null);
        setDraftAccountId(null);
        setTitle("");
        setBody("");
        setDraftTags([]);
        setPillar("");
        setExperiment("");
        editorSnapshot.current = "";
      }
    } catch {
      setError("草稿列表加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleDeleteDraft(draftId: number) {
    try {
      await deleteDraft(draftId);
      setDrafts((prev) => prev.filter((d) => d.id !== draftId));
      if (selectedDraftId === draftId) {
        setSelectedDraftId(null);
        setTitle("");
        setBody("");
      }
      antMessage.success("草稿已删除。");
    } catch {
      antMessage.error("草稿删除失败。");
    }
  }

  function upsertDraft(draft: Draft, mode: AiContentMode = activeMode) {
    setDrafts((current) => {
      const exists = current.some((item) => item.id === draft.id);
      return exists
        ? current.map((item) => (
            item.id === draft.id
              ? {
                  ...item,
                  ...draft,
                  asset_count: draft.asset_count ?? item.asset_count,
                  image_count: draft.image_count ?? item.image_count,
                  video_count: draft.video_count ?? item.video_count,
                  media_ready: draft.media_ready ?? item.media_ready,
                  account_ready: draft.account_ready ?? item.account_ready,
                }
              : item
          ))
        : [draft, ...current];
    });
    selectDraft(draft, mode, true);
  }

  async function handleReviewDraft(
    draft: Draft,
    next: "adopted" | "discarded" | "pending",
  ) {
    setReviewingId(draft.id);
    clearStatus();
    try {
      const updated = await reviewDraft(draft.id, next);
      setDrafts((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      const label =
        next === "adopted" ? "已采用" : next === "discarded" ? "已废弃" : "已放回待审";
      antMessage.success(`草稿 #${updated.id} ${label}。`);
    } catch {
      antMessage.error("更新草稿状态失败。");
    } finally {
      setReviewingId(null);
    }
  }

  async function handleSave() {
    if (!selectedDraft) {
      antMessage.error("请先选择或生成一个草稿。");
      return;
    }
    setIsSaving(true);
    clearStatus();
    try {
      const updated = await updateDraft(selectedDraft.id, {
        title,
        body,
        tags: draftTags,
        pillar,
        experiment,
        ...(draftAccountId ? { platform_account_id: draftAccountId } : {}),
      });
      upsertDraft(updated);
      void loadDraftPreflight(updated.id, draftAccountId);
      antMessage.success(`草稿 #${updated.id} 已保存。`);
    } catch {
      antMessage.error("草稿保存失败。");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleGenerateNote() {
    if (!topic.trim()) {
      antMessage.error("请先填写选题。");
      return;
    }
    setIsGenerating(true);
    clearStatus();
    try {
      const selectedTemplate = templates.find((item) => item.id === templateId);
      const enhance =
        enhanceMiddle && selectedTemplate?.payload?.kind === "positional";
      const draft = await generateNoteWithAi({
        platform: "xhs",
        topic: topic.trim(),
        reference,
        instruction,
        template_id: templateId,
        account_id: draftAccountId ?? undefined,
        ...(enhance ? { enhance_middle: true } : {}),
      });
      upsertDraft(draft as Draft, "generate");
      antMessage.success(`已生成草稿 #${draft.id}，可继续编辑或送入发布中心。`);
    } catch {
      antMessage.error("AI 生成笔记失败，请确认已配置默认文本模型。");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleRewrite() {
    if (!selectedDraft) {
      antMessage.error("请先选择一个草稿。");
      return;
    }
    setIsRewriting(true);
    clearStatus();
    setRewritePreview(null);
    setRewriteOriginal({ title, body });
    try {
      const saved = await updateDraft(selectedDraft.id, { title, body });
      const rewritten = await rewriteDraftWithAi({
        draft_id: saved.id,
        instruction: systemPrompt + "\n" + instruction,
        template_id: templateId,
        account_id: draftAccountId ?? selectedDraft.platform_account_id ?? undefined,
      });
      setRewritePreview({
      title: String(rewritten.title ?? ""),
      body: String(rewritten.body ?? ""),
    });
      antMessage.success("AI 改写完成，标题和正文都已分别提取，确认后再采用。");
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      antMessage.error(d || "AI 改写失败，请确认已配置默认文本模型。");
    } finally {
      setIsRewriting(false);
    }
  }

  function applyRewrite() {
    if (rewritePreview !== null) {
      setTitle(rewritePreview.title || title);
      setBody(rewritePreview.body);
      setRewritePreview(null);
      setRewriteOriginal(null);
      antMessage.success("已采用 AI 改写内容，标题和正文已分别填入。");
    }
  }

  function discardRewrite() {
    const original = rewriteOriginal;
    setRewritePreview(null);
    setRewriteOriginal(null);
    if (original && selectedDraft) {
      setTitle(original.title);
      setBody(original.body);
      // 后端在改写时已经写入了草稿，放弃时需要把原文写回去
      void updateDraft(selectedDraft.id, original).catch(() => undefined);
    }
    antMessage.success("已放弃 AI 改写内容，已恢复原文。");
  }

  async function handleGenerateTitles() {
    if (!body.trim()) {
      antMessage.error("请先填写正文。");
      return;
    }
    setIsPolishingTitles(true);
    clearStatus();
    try {
      const result = await generateTitleOptions({ title, body, count: 5, template_id: templateId, account_id: draftAccountId ?? undefined });
      setTitleOptions(result.items);
      antMessage.success("标题候选已生成。");
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      antMessage.error(d || "标题润色失败，请确认已配置默认文本模型。");
    } finally {
      setIsPolishingTitles(false);
    }
  }

  async function handleGenerateTags() {
    if (!body.trim()) {
      antMessage.error("请先填写正文。");
      return;
    }
    setIsPolishingTags(true);
    clearStatus();
    try {
      const result = await generateTagOptions({ title, body, count: 8, account_id: draftAccountId ?? undefined });
      setTagOptions(result.items);
      antMessage.success("标签候选已生成。");
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      antMessage.error(d || "标签润色失败，请确认已配置默认文本模型。");
    } finally {
      setIsPolishingTags(false);
    }
  }

  async function handleRecommendTopics() {
    if (!selectedDraft) {
      antMessage.error("请先选择一个草稿。");
      return;
    }
    const content = `${title}\n${body}`.trim();
    if (!content) {
      antMessage.error("请先填写标题或正文。");
      return;
    }
    setIsLoadingTopics(true);
    clearStatus();
    try {
      let accountId: number | undefined;
      try {
        const accounts = await fetchAccounts("xhs");
        const account = accounts.find(
          (item) => item.platform === "xhs" && (item.sub_type === "pc" || item.sub_type === "creator"),
        );
        accountId = account?.id;
      } catch {
        // 话题库增强失败不影响热搜匹配
      }
      const data = await recommendXhsTopics({ content, limit: 8, account_id: accountId });
      setTopicRecs(data.items ?? []);
      if (!data.items?.length) {
        antMessage.error("没有匹配到合适的话题，可稍后再试。");
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      antMessage.error(detail || "话题推荐失败（热搜源可能暂时不可用）。");
    } finally {
      setIsLoadingTopics(false);
    }
  }

  function addRecommendedTopic(name: string) {
    if (draftTags.some((tag) => tag.name === name)) return;
    setDraftTags((prev) => [...prev, { id: "", name }]);
    antMessage.success(`已添加话题「${name}」`);
  }

  async function handleScoreTitle() {
    if (!title.trim()) {
      antMessage.error("请先填写标题。");
      return;
    }
    setScoringKind("title");
    clearStatus();
    try {
      setScoreResult(await scoreXhsTitle({ title: title.trim(), body }));
    } catch {
      antMessage.error("标题打分失败，请稍后重试。");
    } finally {
      setScoringKind(null);
    }
  }

  async function handlePreviewScoreTitle() {
    if (!title.trim()) {
      antMessage.error("请先填写标题。");
      return;
    }
    setScoringKind("title");
    clearStatus();
    try {
      setPreviewScore(await scoreXhsTitle({ title: title.trim(), body }));
    } catch {
      antMessage.error("标题打分失败，请稍后重试。");
    } finally {
      setScoringKind(null);
    }
  }

  async function handlePreviewScoreNote() {
    if (!body.trim()) {
      antMessage.error("请先填写正文。");
      return;
    }
    setScoringKind("note");
    clearStatus();
    try {
      setPreviewScore(
        await scoreXhsNote({
          title: title.trim(),
          body,
          tags: draftTags.map((tag) => tag.name).filter(Boolean),
        }),
      );
    } catch {
      antMessage.error("笔记体检失败，请稍后重试。");
    } finally {
      setScoringKind(null);
    }
  }

  async function handleSkillScore() {
    if (!selectedDraft) {
      antMessage.error("请先选择或生成一个草稿，再按 Skill 评分。");
      return;
    }
    if (!body.trim()) {
      antMessage.error("请先填写正文。");
      return;
    }
    setIsScoringSkill(true);
    clearStatus();
    try {
      const saved = await updateDraft(selectedDraft.id, {
        title,
        body,
        tags: draftTags,
        ...(draftAccountId ? { platform_account_id: draftAccountId } : {}),
      });
      upsertDraft(saved);
      setSkillScore(await scoreDraftWithSkill(saved.id));
    } catch {
      antMessage.error("Skill 评分失败，请确认已配置创作 Skill。");
    } finally {
      setIsScoringSkill(false);
    }
  }

  async function sendChat(text?: string) {
    const message = (text ?? chatInput).trim();
    if (!message) return;
    if (!selectedDraft) {
      antMessage.error("请先选择或生成一个草稿，再和草稿助手对话。");
      return;
    }
    const history = chatMessages.slice(-8).map((item) => ({ role: item.role, content: item.content }));
    setChatMessages((prev) => [...prev, { role: "user", content: message }]);
    setChatInput("");
    setIsChatting(true);
    clearStatus();
    try {
      const result = await draftChat({
        draft_id: selectedDraft.id,
        message,
        history,
        style_prompt: systemPrompt,
      });
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant" as const, content: result.reply ?? "" },
      ]);
      setChatPatch(result.patch);
      setChatChanges(result.changes ?? []);
      setChatScore(result.score ?? null);
      setChatMessageId(result.assistant_message_id ?? null);
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "这次对话失败了，请确认默认文本模型可用后重试。" },
      ]);
    } finally {
      setIsChatting(false);
    }
  }

  async function applyChatPatch() {
    if (!chatPatch || !selectedDraft) return;
    setIsApplyingChat(true);
    clearStatus();
    try {
      const result = await applyDraftChat({
        draft_id: selectedDraft.id,
        message_id: chatMessageId,
        patch: chatPatch,
      });
      const applied = result.draft as Draft;
      upsertDraft(applied as Draft);
      setTitle(applied.title || "");
      setBody((applied as Draft).body || "");
      setDraftTags(
        ((applied as Draft).tags || []).map((tag: { id?: string; name: string }) => ({ id: String(tag.id || ""), name: tag.name })),
      );
      if (result.version) {
        const version = result.version;
        setDraftVersions((prev) => [version, ...prev.filter((item) => item.id !== version.id)]);
      }
      setChatPatch(null);
      setChatMessageId(null);
      antMessage.success(`已应用并保存，生成草稿版本 v${result.version.version_no}。`);
    } catch {
      antMessage.error("应用修改失败，请稍后重试。");
    } finally {
      setIsApplyingChat(false);
    }
  }

  async function restoreVersion(versionId: number) {
    if (!selectedDraft) return;
    clearStatus();
    try {
      const result = await restoreDraftVersion(selectedDraft.id, versionId);
      if (result.draft) {
        const applied = result.draft;
        upsertDraft(applied as Draft);
        setTitle(applied.title || "");
        setBody((applied as Draft).body || "");
        setDraftTags(
          ((applied as Draft).tags || []).map((tag: { id?: string; name: string }) => ({ id: String(tag.id || ""), name: tag.name })),
        );
      }
      if (result.version) {
        const version = result.version;
        setDraftVersions((prev) => [
          version,
          ...prev.filter((item) => item.id !== version.id),
        ]);
      }
      antMessage.success(`已恢复内容，并生成新版本 v${result.version?.version_no ?? ""}。`);
    } catch {
      antMessage.error("恢复版本失败，请稍后重试。");
    }
  }

  async function handleScoreNote() {
    if (!body.trim()) {
      antMessage.error("请先填写正文。");
      return;
    }
    setScoringKind("note");
    clearStatus();
    try {
      setScoreResult(
        await scoreXhsNote({
          title: title.trim(),
          body,
          tags: draftTags.map((tag) => tag.name).filter(Boolean),
        }),
      );
    } catch {
      antMessage.error("笔记体检失败，请稍后重试。");
    } finally {
      setScoringKind(null);
    }
  }

  async function handleCheckSensitiveWords() {
    const content = `${title}\n${body}`.trim();
    if (!content) {
      antMessage.error("请先填写标题或正文。");
      return;
    }
    if (content.length > 3000) {
      antMessage.error(`违禁词检测最多 3000 字，当前 ${content.length} 字，请分段检测。`);
      return;
    }
    setIsCheckingWords(true);
    clearStatus();
    try {
      const result = await checkXhsSensitiveWords(content);
      setWordCheck(result);
      if (result.clean) {
        antMessage.success("未检测到违禁词。");
      } else {
        antMessage.success(`检测到 ${result.hit_count} 处风险词，已在下方面板高亮。`);
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      antMessage.error(detail || "违禁词检测失败，请确认数据源已切换为 RedFox。");
    } finally {
      setIsCheckingWords(false);
    }
  }

  async function handleSendToCardStudio() {
    if (!selectedDraft || !body.trim()) {
      antMessage.error("请先填写正文。");
      return;
    }
    // persist first so the card studio receives the latest text
    try {
      await updateDraft(selectedDraft.id, { title, body });
    } catch {
      // non-blocking: still hand over the current editor content
    }
    navigate("/platforms/xhs/write/visual/cards", {
      state: { title: title.trim() || selectedDraft.title, body, draftId: selectedDraft.id },
    });
  }

  async function handleBuildVisualBrief() {
    if (!selectedDraft) {
      antMessage.error("请先选择一个草稿。");
      return;
    }
    setIsBuildingVisualBrief(true);
    clearStatus();
    try {
      const saved = await updateDraft(selectedDraft.id, { title, body });
      upsertDraft(saved);
      const brief = await buildDraftVisualBrief(saved.id);
      setVisualBrief(brief);
      setVisualBriefOpen(true);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      antMessage.error(detail || "生成视觉简报失败，请确认草稿已保存。");
    } finally {
      setIsBuildingVisualBrief(false);
    }
  }

  function openVisualBriefInStudio(kind: "cover" | "illustration") {
    if (!visualBrief) return;
    const prompt =
      kind === "cover" ? (visualBrief.cover?.prompt ?? "") : (visualBrief.illustration?.prompt ?? "");
    const preset = kind === "cover" ? "cover" : "wide";
    setVisualBriefOpen(false);
    navigate(
      `/platforms/xhs/write/visual/images?prompt=${encodeURIComponent(prompt)}&preset=${preset}&draft_id=${visualBrief.draft_id}`,
    );
  }

  async function handleSendToPublish() {
    clearStatus();
    setSendError("");

    if (!canSendToPublish) {
      setSendError(sendBlockReason || "当前草稿还不能送入发布中心。");
      return;
    }
    if (!selectedDraft) {
      setSendError("请先选择一个草稿。");
      return;
    }

    setIsSendingPublish(true);
    try {
      const saved = await updateDraft(selectedDraft.id, {
        title,
        body,
        tags: draftTags,
        pillar,
        experiment,
        ...(draftAccountId ? { platform_account_id: draftAccountId } : {}),
      });
      const job = await sendDraftToPublish(saved.id, {
        publish_mode: "immediate",
      });
      upsertDraft(saved);
      setAssistantOpen(false);
      antMessage.success(`已送入发布中心，发布任务 #${job.id}`);
      navigate(`/platforms/xhs/publish-hub/jobs?job_id=${job.id}`);
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSendError(d || "送发布中心失败，请重试。");
    } finally {
      setIsSendingPublish(false);
    }
  }

  useEffect(() => {
    void loadDrafts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewFilter, originFilter]);

  useEffect(() => {
    if (!initialDraftId) {
      lastDraftQueryRef.current = null;
      return;
    }
    if (lastDraftQueryRef.current === initialDraftId) return;
    const target = drafts.find((draft) => draft.id === initialDraftId);
    if (!target) return;
    lastDraftQueryRef.current = initialDraftId;
    if (target.id !== selectedDraftId) {
      selectDraft(target, activeMode, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDraftId, drafts]);

  useEffect(() => {
    // RedFox 违禁词检测是可选模块：余额为 0 / 未配置 Key 时静默禁用按钮
    void fetchXhsRedfoxStatus()
      .then(setRedfoxStatus)
      .catch(() => setRedfoxStatus(null));
    void fetchAccounts("xhs")
      .then((items) => setAccounts(items))
      .catch(() => setAccounts([]));
    void fetchViralTemplates()
      .then((data) => {
        setTemplates(data.items ?? []);
      })
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    const raw = searchParams.get("template");
    const wanted = raw ? Number(raw) : Number.NaN;
    if (Number.isFinite(wanted) && templates.some((item) => item.id === wanted)) {
      setTemplateId(wanted);
      setActiveMode("generate");
    }
  }, [searchParams, templates]);

  useEffect(() => {
    setStructureCheck(null);
    if (!selectedDraft?.template_id || !canCheckStructure) return;
    let cancelled = false;
    void checkStructure({
      template_id: selectedDraft.template_id,
      draft_id: selectedDraft.id,
    })
      .then((result) => {
        if (!cancelled) setStructureCheck(result);
      })
      .catch(() => {
        if (!cancelled) setStructureCheck(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDraft?.id, selectedDraft?.template_id, selectedDraft?.body, canCheckStructure]);

  async function runStructureCheck(useEditor = false) {
    if (!selectedDraft?.template_id || !canCheckStructure) return;
    setIsCheckingStructure(true);
    try {
      const result = await checkStructure({
        template_id: selectedDraft.template_id,
        ...(useEditor
          ? { title, body }
          : { draft_id: selectedDraft.id }),
      });
      setStructureCheck(result);
    } catch {
      setStructureCheck(null);
      antMessage.warning("结构检查失败：这个模板可能不是位置结构模板");
    } finally {
      setIsCheckingStructure(false);
    }
  }

  useEffect(() => {
    if (!draftAccountId) {
      setActiveSkill(null);
      return;
    }
    let cancelled = false;
    void fetchCurrentCreationSkill(draftAccountId)
      .then((result) => {
        if (!cancelled) setActiveSkill(result.skill);
      })
      .catch(() => {
        if (!cancelled) setActiveSkill(null);
      });
    return () => {
      cancelled = true;
    };
  }, [draftAccountId]);

  useEffect(() => {
    if (!selectedDraftId) {
      setDraftVersions([]);
      setChatMessages([{ role: "assistant", content: CHAT_WELCOME }]);
      setChatPatch(null);
      setChatMessageId(null);
      setChatScore(null);
      setChatChanges([]);
      return;
    }
    let cancelled = false;
    void Promise.all([fetchDraftChat(selectedDraftId), fetchDraftVersions(selectedDraftId)])
      .then(([chat, versions]) => {
        if (cancelled) return;
        setDraftVersions(versions.items);
        if (chat.items.length) {
          setChatMessages(
        chat.items.map((item) => ({
          role: item.role === "assistant" ? ("assistant" as const) : ("user" as const),
          content: item.content,
        })),
      );
          const lastPatch = [...chat.items].reverse().find((item) => item.role === "assistant" && item.patch);
          if (lastPatch) {
            setChatPatch(lastPatch.patch);
            setChatMessageId(lastPatch.id ?? null);
            setChatScore(lastPatch.score ?? null);
            setChatChanges([]);
          } else {
            setChatPatch(null);
            setChatMessageId(null);
            setChatScore(null);
          }
        } else {
          setChatMessages([{ role: "assistant", content: CHAT_WELCOME }]);
          setChatPatch(null);
          setChatMessageId(null);
          setChatScore(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDraftVersions([]);
          setChatMessages([{ role: "assistant", content: CHAT_WELCOME }]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDraftId]);

  useEffect(() => {
    if (!selectedDraft) {
      setSourceNote(null);
      setSourceAssets([]);
      return;
    }
    let cancelled = false;
    (async () => {
      // Load assets from draft (not source note)
      try {
        const assetsResult = await fetchDraftAssets(selectedDraft.id);
        if (!cancelled) setSourceAssets(assetsResult.items);
      } catch {
        if (!cancelled) setSourceAssets([]);
      }

      // Load source note info for display only
      if (selectedDraft.source_note_id) {
        try {
          const note = await fetchSavedNote(selectedDraft.source_note_id, true);
          if (!cancelled) setSourceNote(note);
        } catch {
          if (!cancelled) setSourceNote(null);
        }
      } else {
        if (!cancelled) setSourceNote(null);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedDraft?.id, selectedDraft?.source_note_id]);

  useEffect(() => {
    if (!selectedDraftId) {
      setDraftPreflight(null);
      return;
    }
    let cancelled = false;
    setIsPreflightLoading(true);
    fetchDraftPreflight(selectedDraftId, draftAccountId)
      .then((result) => {
        if (!cancelled) setDraftPreflight(result);
      })
      .catch(() => {
        if (!cancelled) setDraftPreflight(null);
      })
      .finally(() => {
        if (!cancelled) setIsPreflightLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDraftId, draftAccountId, sourceAssets.length]);

  useEffect(() => {
    if (!publishIntent || !draftPreflight) return;
    const target = document.getElementById("publish-preflight");
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [publishIntent, draftPreflight]);

  useEffect(() => {
    if (uploadModalOpen) {
      void fetchUserImages().then(r => setUserImages(r.items)).catch(() => {});
      void fetchGeneratedImageAssets().then(r => setAiAssets(r.items)).catch(() => {});
      setSelectedAssetUrls([]);
    }
  }, [uploadModalOpen]);

  useEffect(() => {
    if (refPickerOpen) {
      void fetchUserImages().then((r) => setUserImages(r.items)).catch(() => {});
      void fetchGeneratedImageAssets().then((r) => setAiAssets(r.items)).catch(() => {});
    }
  }, [refPickerOpen]);

  // ---- Rewrite mode: queue + editor, assistant lives in a drawer ----
  function renderRewriteMode() {
    const editorSpan = 24 - (queueVisible ? 6 : 0);
    return (
      <>
      <Space wrap style={{ marginBottom: 12, justifyContent: "flex-end", width: "100%" }}>
        <Button size="small" onClick={() => setQueueVisible((value) => !value)}>
          {queueVisible ? "收起草稿队列" : "展开草稿队列"}
        </Button>
        <Button size="small" icon={<RobotOutlined />} onClick={() => { setSendError(""); setAssistantOpen(true); }}>
          草稿助手
        </Button>
      </Space>
      <Row gutter={16} align="stretch" style={{ alignItems: "stretch" }}>
        {/* Col 1: Draft queue */}
        {queueVisible ? (
          <Col xs={24} lg={6}>
            <DraftQueue
              drafts={drafts}
              selectedDraftId={selectedDraftId}
              isLoading={isLoading}
              reviewFilter={reviewFilter}
              originFilter={originFilter}
              readinessFilter={readinessFilter}
              onReviewFilterChange={(value) => confirmDiscard(() => setReviewFilter(value))}
              onOriginFilterChange={(value) => confirmDiscard(() => setOriginFilter(value))}
              onReadinessFilterChange={(value) => confirmDiscard(() => setReadinessFilter(value))}
              onClearFilters={() => {
                setReviewFilter("all");
                setOriginFilter("all");
                setReadinessFilter("all");
              }}
              onGenerateNew={() => setActiveMode("generate")}
              onSelect={selectDraft}
              onDelete={(id) => void handleDeleteDraft(id)}
              onGoToImages={goToDraftImages}
            />
          </Col>
        ) : null}

        {/* Col 2: Main editor */}
        <Col xs={24} lg={editorSpan} style={{ display: "flex", flexDirection: "column" }}>
          {selectedDraft && (selectedDraft.template_id || selectedDraft.topic_id) ? (
            <Card size="small" style={{ marginBottom: 16 }}>
              <Space wrap size={8}>
                <Text type="secondary" style={{ fontSize: 12 }}>草稿来源</Text>
                {selectedDraft.topic_id ? (
                  <Link to="/platforms/xhs/plan">
                    <Tag color="blue" style={{ cursor: "pointer", marginInlineEnd: 0 }}>
                      来源选题 #{selectedDraft.topic_id}
                    </Tag>
                  </Link>
                ) : null}
                {selectedDraft.template_id ? (
                  <>
                    <Link to="/platforms/xhs/refine/templates">
                      <Tag color="purple" style={{ cursor: "pointer", marginInlineEnd: 0 }}>
                        {canCheckStructure ? "结构模板：" : "标题/要点模板："}
                        {selectedDraftTemplate?.name ?? `#${selectedDraft.template_id}`}
                      </Tag>
                    </Link>
                    {canCheckStructure ? (
                      <>
                    {structureCheck ? (
                      <Popover
                        title="结构覆盖检查"
                        content={
                          <div style={{ maxWidth: 340 }}>
                            {structureCheck.positions.map((item) => (
                              <div key={item.position}>
                                {STRUCTURE_POSITION_LABELS[item.position] ?? item.position}：
                                {item.strict_match ? "✓" : item.soft_match ? "△" : "✗"}{" "}
                                {item.detected}
                                <Text type="secondary">
                                  （期望「{item.expected}」，置信度{" "}
                                  {Math.round(item.confidence * 100)}%）
                                </Text>
                              </div>
                            ))}
                            <div style={{ marginTop: 6 }}>
                              实际骨架：{structureCheck.actual_skeleton}
                            </div>
                            {structureCheck.middle_elements.length ? (
                              <div style={{ marginTop: 6 }}>
                                中段要素：
                                {structureCheck.middle_elements.map((item) => (
                                  <Tag
                                    key={item.label}
                                    color={item.present ? "green" : "default"}
                                    style={{ marginInlineEnd: 4 }}
                                  >
                                    {item.label}
                                    {item.pct != null ? ` ${item.pct}%` : ""}
                                    {item.present ? " ✓" : " ✗"}
                                  </Tag>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        }
                      >
                        <Tag
                          color={
                            structureCheck.coverage >= 67
                              ? "green"
                              : structureCheck.soft_coverage >= 67
                                ? "gold"
                                : "red"
                          }
                          style={{ cursor: "help", marginInlineEnd: 0 }}
                        >
                          结构 {structureCheck.matched}/{structureCheck.total}（
                          {structureCheck.coverage}%）
                        </Tag>
                      </Popover>
                    ) : null}
                    <Button
                      size="small"
                      type="link"
                      loading={isCheckingStructure}
                      onClick={() => void runStructureCheck(true)}
                    >
                      按当前正文复查
                    </Button>
                      </>
                    ) : null}
                  </>
                ) : null}
              </Space>
            </Card>
          ) : null}
          {selectedDraft ? (
            <DraftPreflightCard
              preflight={draftPreflight}
              isLoading={isPreflightLoading}
              sendError={sendError}
              accountBound={accountBound}
              assetCount={sourceAssets.length}
              contentReady={contentReady}
              tagCount={draftTags.length}
              canSendToPublish={canSendToPublish}
              isSending={isSendingPublish}
              onRefresh={() => void loadDraftPreflight()}
              onBindAccount={() => navigate("/settings/accounts")}
              onUploadAssets={() => setUploadModalOpen(true)}
              onSend={handleSendToPublish}
            />
          ) : null}
          {sourceNote && (
            <Card
              title="草稿内容"
              size="small"
              style={{ marginBottom: 16 }}
              extra={
                <a
                  href={getNoteUrl(sourceNote)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button type="link" size="small" icon={<LinkOutlined />}>查看原文</Button>
                </a>
              }
            >
              <Text strong style={{ display: "block", marginBottom: 4 }}>{sourceNote.title}</Text>
              <Paragraph
                ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}
                type="secondary"
                style={{ marginBottom: 8, fontSize: 13 }}
              >
                {sourceNote.content}
              </Paragraph>

              <div style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    <FileImageOutlined /> 图片素材 ({imageAssets.length}){imageAssets.length ? " — 拖拽调整顺序" : " — 从图片素材选图或本地上传"}
                  </Text>
                  <Button size="small" type="link" icon={<PictureOutlined />} onClick={() => setUploadModalOpen(true)}>
                    从素材库选图
                  </Button>
                </div>
                  <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                    <SortableContext items={imageAssets.map((a) => a.id)} strategy={horizontalListSortingStrategy}>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                        {imageAssets.map((asset) => (
                          <SortableRewriteImage
                            key={asset.id}
                            asset={asset}
                            onEdit={() => { setOptimizeAssetId(asset.id); setOptimizeModalOpen(true); }}
                            onRemove={() => handleRemoveAsset(asset.id)}
                            onView={() => setPreviewImage(asset.url || asset.local_path || null)}
                          />
                        ))}
                        <div
                          onClick={() => setUploadModalOpen(true)}
                          style={{
                            width: 60, height: 60, borderRadius: 8, border: `1px dashed ${token.colorBorder}`,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            cursor: "pointer", background: token.colorFillQuaternary,
                          }}
                        >
                          <PlusOutlined style={{ fontSize: 20, color: token.colorTextTertiary }} />
                        </div>
                      </div>
                    </SortableContext>
                  </DndContext>
                </div>

              {hasVideoAssets && (
                <div style={{ marginBottom: 8 }}>
                  {sourceAssets.filter((a) => a.asset_type === "video").map((asset) => (
                    <div key={asset.id} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <Button
                        type="link" size="small" icon={<PlayCircleOutlined />}
                        href={asset.url || sourceNote.video_url} target="_blank" rel="noopener noreferrer"
                      >
                        查看视频
                      </Button>
                      <Button type="text" size="small" icon={<EditOutlined />}
                        onClick={() => { setOptimizeAssetId(asset.id); setOptimizeModalOpen(true); }}
                        style={{ color: token.colorPrimary }}
                      />
                    </div>
                  ))}
                </div>
              )}

              <Space size={4}>
                <Tag color={hasVideoAssets ? "purple" : "blue"}>
                  {hasVideoAssets ? "视频" : "图文"}
                </Tag>
                {hasImageAssets && (
                  <>
                    <PictureOutlined style={{ color: token.colorTextTertiary, fontSize: 12 }} />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {sourceAssets.filter((a) => a.asset_type === "image").length} 张图片
                    </Text>
                  </>
                )}
              </Space>
            </Card>
          )}
          {!sourceNote && (
            <Card
              title="图片素材"
              size="small"
              style={{ marginBottom: 16 }}
              extra={
                <Button size="small" type="link" icon={<PictureOutlined />} onClick={() => setUploadModalOpen(true)}>
                  从素材库选图
                </Button>
              }
            >
              {imageAssets.length === 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  还没有图片素材，可从图片素材选图或本地上传。
                </Text>
              ) : (
                <Space size={8} wrap>
                  {imageAssets.map((asset) => (
                    <div
                      key={asset.id}
                      style={{
                        width: 60,
                        height: 60,
                        borderRadius: 8,
                        overflow: "hidden",
                        border: "1px solid rgba(127,127,127,.25)",
                      }}
                    >
                      <img
                        src={asset.url || (asset.local_path ? `/api/files/media/${asset.local_path}` : "")}
                        style={{ width: "100%", height: "100%", objectFit: "cover" }}
                        referrerPolicy="no-referrer"
                      />
                    </div>
                  ))}
                  <div
                    onClick={() => setUploadModalOpen(true)}
                    style={{
                      width: 60,
                      height: 60,
                      borderRadius: 8,
                      border: `1px dashed ${token.colorBorder}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      cursor: "pointer",
                      background: token.colorFillQuaternary,
                    }}
                  >
                    <PlusOutlined style={{ fontSize: 20, color: token.colorTextTertiary }} />
                  </div>
                </Space>
              )}
            </Card>
          )}
          <Card
            title="编辑器"
            style={{ marginBottom: 16, flex: 1, display: "flex", flexDirection: "column" }}
            styles={{ body: { flex: 1, display: "flex", flexDirection: "column" } }}
            extra={
              <Space size={4} wrap>
                {selectedDraft ? (
                  selectedDraft.review_status === "adopted" ? (
                    <Tag color="blue" style={{ marginInlineEnd: 0 }}>已采用</Tag>
                  ) : (
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      loading={reviewingId === selectedDraft.id}
                      onClick={() => void handleReviewDraft(selectedDraft, "adopted")}
                      title="标记为已采用，进入可发布状态"
                    >
                      采用这篇
                    </Button>
                  )
                ) : null}
                {selectedDraft && selectedDraft.review_status !== "discarded" ? (
                  <Popconfirm
                    title="废弃这篇草稿？"
                    description="废弃后仍保留在列表，可随时恢复为待审。"
                    okText="废弃"
                    cancelText="取消"
                    onConfirm={() => void handleReviewDraft(selectedDraft, "discarded")}
                  >
                    <Button size="small" loading={reviewingId === selectedDraft.id}>
                      废弃
                    </Button>
                  </Popconfirm>
                ) : null}
                {selectedDraft && selectedDraft.review_status === "discarded" ? (
                  <Button
                    size="small"
                    loading={reviewingId === selectedDraft.id}
                    onClick={() => void handleReviewDraft(selectedDraft, "pending")}
                  >
                    恢复待审
                  </Button>
                ) : null}
                <Button
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => {
                    setPreviewScore(null);
                    setPreviewOpen(true);
                  }}
                >
                  预览
                </Button>
                <Button size="small" icon={<PictureOutlined />} onClick={() => setImageWriterOpen(true)}>
                  从图片写文案
                </Button>
              </Space>
            }
          >
            <Form layout="vertical" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
              <Form.Item label="绑定账号" style={{ marginBottom: 16 }}>
                <Select
                  allowClear
                  value={draftAccountId ?? undefined}
                  onChange={(value) => setDraftAccountId(value ?? null)}
                  placeholder="选择这个草稿要发布的账号"
                  options={accounts
                    .filter((account) => account.platform === "xhs")
                    .map((account) => ({
                      value: account.id,
                      label: `${account.nickname || `账号 ${account.id}`} · ${
                        account.sub_type === "creator" ? "Creator" : account.sub_type === "pc" ? "PC" : "未知"
                      }`,
                    }))}
                />
                <Space direction="vertical" size={4}>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    绑定后，AI 生成/改写会读取该账号的当前创作 Skill。
                  </Text>
                  {activeSkill ? (
                    <Tag color="blue">
                      Skill：{activeSkill.name} {activeSkill.version}
                    </Tag>
                  ) : (
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {draftAccountId ? "该账号还没有创作 Skill" : "选择账号后显示当前 Skill"}
                    </Text>
                  )}
                </Space>
              </Form.Item>
              <Form.Item label="标题" style={{ marginBottom: 16 }}>
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="生成或选择一个标题"
                  size="large"
                />
              </Form.Item>
              <Form.Item label="正文" style={{ marginBottom: 16, flex: 1, display: "flex", flexDirection: "column" }}>
                <TextArea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="正文生成后可在这里继续编辑。"
                  rows={20}
                  style={{ fontFamily: "monospace", flex: 1, minHeight: 360, resize: "none" }}
                />
              </Form.Item>
              <Form.Item label="标签" style={{ marginBottom: 16 }}>
                <Space size={[4, 8]} wrap>
                  {draftTags.map((tag) => (
                    <Tag
                      key={tag.id || tag.name}
                      closable
                      onClose={() => setDraftTags((prev) => prev.filter((t) => t.name !== tag.name))}
                      color="blue"
                    >
                      #{tag.name}
                    </Tag>
                  ))}
                  {isAddingTag ? (
                    <Input
                      size="small"
                      style={{ width: 120 }}
                      value={newTagInput}
                      onChange={(e) => setNewTagInput(e.target.value)}
                      onPressEnter={() => {
                        const name = newTagInput.trim();
                        if (name && !draftTags.some((t) => t.name === name)) {
                          setDraftTags((prev) => [...prev, { id: "", name }]);
                        }
                        setNewTagInput("");
                        setIsAddingTag(false);
                      }}
                      onBlur={() => {
                        const name = newTagInput.trim();
                        if (name && !draftTags.some((t) => t.name === name)) {
                          setDraftTags((prev) => [...prev, { id: "", name }]);
                        }
                        setNewTagInput("");
                        setIsAddingTag(false);
                      }}
                      autoFocus
                      placeholder="输入标签"
                    />
                  ) : (
                    <Tag
                      style={{ cursor: "pointer", borderStyle: "dashed" }}
                      onClick={() => setIsAddingTag(true)}
                    >
                      + 添加标签
                    </Tag>
                  )}
                </Space>
              </Form.Item>
              <Form.Item label="内容支柱 / 实验标签" style={{ marginBottom: 16 }}>
                <Space wrap>
                  <Input
                    addonBefore="支柱"
                    value={pillar}
                    onChange={(e) => setPillar(e.target.value)}
                    placeholder="例如：一人公司"
                    style={{ width: 220 }}
                  />
                  <Input
                    addonBefore="实验"
                    value={experiment}
                    onChange={(e) => setExperiment(e.target.value)}
                    placeholder="例如：真实报价"
                    style={{ width: 220 }}
                  />
                </Space>
              </Form.Item>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                onClick={handleSave}
                loading={isSaving}
                disabled={!selectedDraft}
              >
                保存
              </Button>
            </Form>
          </Card>
        </Col>

        {/* AI assistant drawer: keeps the editor at full width until needed */}
        <Drawer
          title="草稿助手"
          placement="right"
          size="min(440px, 100vw)"
          open={assistantOpen}
          onClose={() => setAssistantOpen(false)}
          styles={{ body: { paddingTop: 12 } }}
          footer={
            <AssistantFooter
              sendError={sendError}
              canSendToPublish={canSendToPublish}
              sendBlockReason={sendBlockReason}
              isSendingPublish={isSendingPublish}
              canSendToCardStudio={Boolean(selectedDraft) && Boolean(body.trim())}
              onSendToPublish={handleSendToPublish}
              onSendToCardStudio={handleSendToCardStudio}
              onGoPublishHub={() => navigate("/platforms/xhs/publish-hub/jobs")}
            />
          }
        >
            <AssistantChat
              hasDraft={Boolean(selectedDraft)}
              messages={chatMessages}
              isChatting={isChatting}
              input={chatInput}
              onInputChange={setChatInput}
              onSend={(prompt) => void sendChat(prompt)}
              score={chatScore}
              onClose={() => setAssistantOpen(false)}
            />

            {chatPatch ? (
              <AssistantPatchCard
                patch={chatPatch}
                changes={chatChanges}
                isApplying={isApplyingChat}
                onApply={() => void applyChatPatch()}
                onDiscard={() => setChatPatch(null)}
              />
            ) : null}

            <AssistantVersionList
              versions={draftVersions}
              onRestore={(versionId) => void restoreVersion(versionId)}
            />

            <AssistantTools
              systemPrompt={systemPrompt}
              setSystemPrompt={setSystemPrompt}
              templateId={templateId}
              setTemplateId={setTemplateId}
              activeTemplates={activeTemplates}
              templates={templates}
              activeSkill={activeSkill}
              instruction={instruction}
              setInstruction={setInstruction}
              handleRewrite={handleRewrite}
              isRewriting={isRewriting}
              rewritePreview={rewritePreview}
              title={title}
              applyRewrite={applyRewrite}
              discardRewrite={discardRewrite}
              handleGenerateTitles={handleGenerateTitles}
              isPolishingTitles={isPolishingTitles}
              handleGenerateTags={handleGenerateTags}
              isPolishingTags={isPolishingTags}
              handleRecommendTopics={handleRecommendTopics}
              isLoadingTopics={isLoadingTopics}
              scoringKind={scoringKind}
              handleScoreTitle={handleScoreTitle}
              handleScoreNote={handleScoreNote}
              handleSkillScore={handleSkillScore}
              isScoringSkill={isScoringSkill}
              handleCheckSensitiveWords={handleCheckSensitiveWords}
              isCheckingWords={isCheckingWords}
              redfoxStatus={redfoxStatus}
              handleBuildVisualBrief={handleBuildVisualBrief}
              isBuildingVisualBrief={isBuildingVisualBrief}
              selectedDraft={selectedDraft}
              scoreResult={scoreResult}
              setScoreResult={setScoreResult}
              skillScore={skillScore}
              setSkillScore={setSkillScore}
              topicRecs={topicRecs}
              addRecommendedTopic={addRecommendedTopic}
              wordCheck={wordCheck}
              setWordCheck={setWordCheck}
              titleOptions={titleOptions}
              setTitle={setTitle}
              tagOptions={tagOptions}
              draftTags={draftTags}
              setDraftTags={setDraftTags}
            />

        </Drawer>

        {/* Optimize modal */}
        <Modal
          title="素材优化"
          open={optimizeModalOpen}
          onCancel={() => { setOptimizeModalOpen(false); setOptimizeAssetId(null); setOptimizePrompt(""); setOptimizeRefImages([]); setOptimizeResult(null); }}
          footer={null}
          width={600}
        >
          {(() => {
            const asset = sourceAssets.find((a) => a.id === optimizeAssetId);
            if (!asset) return <Text type="secondary">素材不存在</Text>;
            const isImage = asset.asset_type === "image";
            return (
              <div>
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={12}>
                    <div style={{ padding: 8, background: token.colorFillQuaternary, borderRadius: 8, textAlign: "center" }}>
                      <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>当前素材</Text>
                      {isImage ? (
                        <Image
                          src={asset.url || asset.local_path}
                          width={180}
                          height={180}
                          style={{ objectFit: "contain", borderRadius: 8 }}
                          referrerPolicy="no-referrer"
                          preview={{ mask: <EyeOutlined style={{ fontSize: 16 }} /> }}
                        />
                      ) : (
                        <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <Space direction="vertical" align="center"><PlayCircleOutlined style={{ fontSize: 32, color: token.colorPrimary }} /><Text style={{ fontSize: 12 }}>视频</Text></Space>
                        </div>
                      )}
                    </div>
                  </Col>
                  <Col span={12}>
                    <div style={{ padding: 8, background: token.colorFillQuaternary, borderRadius: 8, textAlign: "center" }}>
                      <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>优化后预览</Text>
                      {optimizeResult ? (
                        <Image
                          src={optimizeResult}
                          width={180}
                          height={180}
                          style={{ objectFit: "contain", borderRadius: 8 }}
                          referrerPolicy="no-referrer"
                          preview={{ mask: <EyeOutlined style={{ fontSize: 16 }} /> }}
                        />
                      ) : (
                        <div style={{ width: 180, height: 180, margin: "0 auto", border: `1px dashed ${token.colorBorder}`, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>{isOptimizing ? "生成中..." : "等待生成"}</Text>
                        </div>
                      )}
                    </div>
                  </Col>
                </Row>

                {isImage ? (
                  <div>
                    <div style={{ marginBottom: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>额外参考图（可选）</Text>
                      <Space size={8} wrap>
                        {optimizeRefImages.map((url, idx) => (
                          <div key={idx} style={{ position: "relative", width: 40, height: 40, borderRadius: 8, overflow: "hidden", border: `1px solid ${token.colorBorder}` }}>
                            <img src={url} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                            <Button type="text" danger size="small" icon={<DeleteOutlined />}
                              onClick={() => setOptimizeRefImages((prev) => prev.filter((_, i) => i !== idx))}
                              style={{ position: "absolute", top: -4, right: -4, fontSize: 8, width: 14, height: 14, minWidth: 14, padding: 0, background: "rgba(0,0,0,.6)", borderRadius: "50%" }}
                            />
                          </div>
                        ))}
                        <div
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => setRefPickerOpen(true)}
                          style={{ width: 40, height: 40, borderRadius: 8, border: `1px dashed ${token.colorBorder}`, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", background: token.colorFillQuaternary }}
                        >
                          <PlusOutlined style={{ fontSize: 14, color: token.colorTextTertiary }} />
                        </div>
                      </Space>
                    </div>
                    <Input.TextArea
                      value={optimizePrompt}
                      onChange={(e) => setOptimizePrompt(e.target.value)}
                      placeholder="描述你想要的润色效果，如：提升画面清晰度和色彩饱和度，增加小红书风格滤镜..."
                      rows={3}
                      style={{ marginBottom: 12 }}
                      disabled={isOptimizing}
                    />
                    <Space direction="vertical" style={{ width: "100%" }} size={8}>
                      <Button
                        block
                        type="primary"
                        icon={<HighlightOutlined />}
                        loading={isOptimizing}
                        onClick={async () => {
                          if (!optimizePrompt.trim()) { antMessage.warning("请输入润色提示词"); return; }
                          setIsOptimizing(true); setOptimizeResult(null);
                          try {
                            const refImages = [asset.url || asset.local_path, ...optimizeRefImages];
                            const fullPrompt = `基于提供的第一张原图进行润色修改。要求：${optimizePrompt.trim()}`;
                            const result = await generateImageWithAi({
                              prompt: fullPrompt,
                              reference_images: refImages.filter(Boolean) as string[],
                              save_to_assets: false,
                            });
                            setOptimizeResult(result.url);
                            antMessage.success("图片润色完成");
                          } catch {
                            antMessage.error("图片润色失败，请确认已配置图片生成模型");
                          } finally { setIsOptimizing(false); }
                        }}
                      >
                        图片润色
                      </Button>
                      {optimizeResult && (
                        <Button
                          block
                          onClick={() => {
                            const draftId = selectedDraft?.id;
                            if (draftId && optimizeAssetId && optimizeAssetId > 0) {
                              void updateDraftAsset(draftId, optimizeAssetId, { url: optimizeResult!, local_path: "" }).then((saved) => {
                                setSourceAssets((prev) => prev.map((a) => a.id === optimizeAssetId ? saved : a));
                              }).catch(() => {
                                setSourceAssets((prev) => prev.map((a) => a.id === optimizeAssetId ? { ...a, url: optimizeResult!, local_path: "" } : a));
                              });
                            } else {
                              setSourceAssets((prev) => prev.map((a) => a.id === optimizeAssetId ? { ...a, url: optimizeResult!, local_path: "" } : a));
                            }
                            setOptimizeModalOpen(false); setOptimizeAssetId(null); setOptimizePrompt(""); setOptimizeRefImages([]); setOptimizeResult(null);
                            antMessage.success("已替换为润色后的图片");
                          }}
                        >
                          替换当前素材
                        </Button>
                      )}
                    </Space>
                  </div>
                ) : (
                  <Button block icon={<VideoCameraOutlined />} disabled>
                    视频润色（即将上线）
                  </Button>
                )}
              </div>
            );
          })()}
        </Modal>

        <Modal
          open={visualBriefOpen}
          title={visualBrief ? `视觉简报 · ${visualBrief.title}` : "视觉简报"}
          onCancel={() => setVisualBriefOpen(false)}
          width={680}
          footer={
            <Space wrap>
              <Button onClick={() => setVisualBriefOpen(false)}>关闭</Button>
              {visualBrief ? (
                <Button type="primary" onClick={() => openVisualBriefInStudio("cover")}>
                  去图片素材做封面
                </Button>
              ) : null}
            </Space>
          }
        >
          {visualBrief ? (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Alert
                type="info"
                showIcon
                message="这是视觉 brief，不会直接出图"
                description="到图片素材生成后，回到草稿页从素材里把图片加入这篇笔记。"
              />
              <Space wrap size={4}>
                <Tag color="purple">风格：{visualBrief.style}</Tag>
                <Tag color="blue">顺序：{(visualBrief.sequence ?? []).join(" → ")}</Tag>
                {visualBrief.requires_exact_title ? <Tag color="gold">封面需要精确标题</Tag> : null}
              </Space>
              <Space wrap size={4}>
                {(visualBrief.experts ?? []).map((expert: VisualBriefExpert) => (
                  <Tag key={expert.key} title={`${expert.purpose}：${expert.reason}`}>
                    {expert.label}
                  </Tag>
                ))}
              </Space>
              <Card
                size="small"
                title={`封面 · ${(visualBrief.cover?.ratio ?? "")}`}
                extra={
                  <Button size="small" onClick={() => openVisualBriefInStudio("cover")}>
                    去生成
                  </Button>
                }
              >
                <Text type="secondary" style={{ fontSize: 12 }}>
                  画面文字：{(visualBrief.cover?.text_overlay ?? "") || "无"}
                </Text>
                <Paragraph
                  copyable={{ text: (visualBrief.cover?.prompt ?? ""), tooltips: ["复制提示词", "已复制"] }}
                  style={{ margin: "6px 0", fontSize: 13 }}
                >
                  {(visualBrief.cover?.prompt ?? "")}
                </Paragraph>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  避免：{(visualBrief.cover?.negative_prompt ?? "")}
                </Text>
              </Card>
              <Card
                size="small"
                title={`正文配图 · ${(visualBrief.illustration?.ratio ?? "")}`}
                extra={
                  <Button size="small" onClick={() => openVisualBriefInStudio("illustration")}>
                    去生成
                  </Button>
                }
              >
                <Paragraph
                  copyable={{ text: (visualBrief.illustration?.prompt ?? ""), tooltips: ["复制提示词", "已复制"] }}
                  style={{ margin: 0, fontSize: 13 }}
                >
                  {(visualBrief.illustration?.prompt ?? "")}
                </Paragraph>
              </Card>
              {(visualBrief.router?.boundaries ?? []).length ? (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>边界</Text>
                  {(visualBrief.router?.boundaries ?? []).map((item: string) => (
                    <div key={item}>
                      <Text type="secondary" style={{ fontSize: 12 }}>· {item}</Text>
                    </div>
                  ))}
                </div>
              ) : null}
              <Text type="secondary" style={{ fontSize: 12 }}>{String(visualBrief.hint ?? "")}</Text>
            </Space>
          ) : (
            <Spin />
          )}
        </Modal>

        {/* Reference image picker modal */}
        <Modal title="选择参考图" open={refPickerOpen} onCancel={() => { setRefPickerOpen(false); setRefPickerUrlInput(""); }} footer={null} width={560}>
          <Tabs size="small" items={[
            {
              key: "user",
              label: "普通图片资产",
              children: userImages.length === 0 ? <Text type="secondary">暂无</Text> : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
                  {userImages.map((img) => (
                    <div key={img.file_name} onClick={() => { setOptimizeRefImages((prev) => [...prev, img.url]); setRefPickerOpen(false); }}
                      style={{ width: 60, height: 60, borderRadius: 8, overflow: "hidden", cursor: "pointer", border: "2px solid transparent" }}>
                      <img src={img.url} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                    </div>
                  ))}
                </div>
              ),
            },
            {
              key: "ai",
              label: "图片素材",
              children: aiAssets.length === 0 ? <Text type="secondary">暂无素材</Text> : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
                  {aiAssets.filter((a) => a.file_path.startsWith("http") || a.file_path.startsWith("/api/files/media/")).map((asset) => (
                    <div key={asset.id} onClick={() => { setOptimizeRefImages((prev) => [...prev, asset.file_path]); setRefPickerOpen(false); }}
                      style={{ width: 60, height: 60, borderRadius: 8, overflow: "hidden", cursor: "pointer", border: "2px solid transparent" }}>
                      <img src={asset.file_path} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                    </div>
                  ))}
                </div>
              ),
            },
            {
              key: "url",
              label: "URL",
              children: (
                <Space.Compact style={{ width: "100%" }}>
                  <Input placeholder="粘贴图片 URL" value={refPickerUrlInput} onChange={(e) => setRefPickerUrlInput(e.target.value)} />
                  <Button type="primary" onClick={() => {
                    const v = refPickerUrlInput.trim();
                    if (v && (v.startsWith("http://") || v.startsWith("https://") || v.startsWith("/api/"))) {
                      setOptimizeRefImages((prev) => [...prev, v]);
                      setRefPickerUrlInput("");
                      setRefPickerOpen(false);
                    }
                  }}>添加</Button>
                </Space.Compact>
              ),
            },
          ]} />
        </Modal>

        {/* Upload modal */}
        <Modal title="上传素材" open={uploadModalOpen} onCancel={() => setUploadModalOpen(false)} footer={null} width={480}>
          <Upload.Dragger
            accept=".jpg,.jpeg,.png,.gif,.webp,.mp4,.mov,.avi,.mkv"
            multiple
            showUploadList={false}
            beforeUpload={(file) => handleFileUpload(file as File)}
            style={{ marginBottom: 12 }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text" style={{ fontSize: 13 }}>
              点击或拖拽文件上传
            </p>
            <p className="ant-upload-hint" style={{ fontSize: 12 }}>
              支持 JPG / PNG / GIF / WEBP / MP4 / MOV
            </p>
          </Upload.Dragger>
          <div style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: "block" }}>或粘贴链接</Text>
            <Space.Compact style={{ width: "100%" }}>
              <Input
                placeholder="粘贴图片或视频链接"
                prefix={<LinkOutlined />}
                value={assetUrl}
                onChange={(e) => setAssetUrl(e.target.value)}
                onPressEnter={handleUrlAdd}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleUrlAdd}
              >
                添加
              </Button>
            </Space.Compact>
          </div>

          <Divider style={{ margin: "12px 0" }}>或从图片资产选择</Divider>

          <Tabs size="small" items={[
            {
              key: "user",
              label: "普通图片资产",
              children: userImages.length === 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>暂无普通图片资产，请先在图片素材上传</Text>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
                  {userImages.map((img) => (
                    <div key={img.file_name} onClick={() => toggleAssetUrl(img.url)}
                      style={{
                        width: 60, height: 60, borderRadius: 8, overflow: "hidden", cursor: "pointer",
                        border: selectedAssetUrls.includes(img.url) ? `2px solid ${token.colorPrimary}` : "2px solid transparent",
                      }}>
                      <img src={img.url} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                    </div>
                  ))}
                </div>
              ),
            },
            {
              key: "ai",
              label: "图片素材",
              children: aiAssets.length === 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>暂无素材，请先在「图片素材」生成、上传或导出卡片</Text>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
                  {aiAssets.filter(a => a.file_path.startsWith("http") || a.file_path.startsWith("/api/files/media/")).map((asset) => (
                    <div key={asset.id} onClick={() => toggleAssetUrl(asset.file_path)}
                      style={{
                        width: 60, height: 60, borderRadius: 8, overflow: "hidden", cursor: "pointer",
                        border: selectedAssetUrls.includes(asset.file_path) ? `2px solid ${token.colorPrimary}` : "2px solid transparent",
                      }}>
                      <img src={asset.file_path} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                    </div>
                  ))}
                </div>
              ),
            },
          ]} />

          {selectedAssetUrls.length > 0 && (
            <Button type="primary" block style={{ marginTop: 12 }} onClick={handleAddSelectedAssets}>
              添加选中的 {selectedAssetUrls.length} 个图片
            </Button>
          )}
        </Modal>

        {/* Image preview */}
        {previewImage && (
          <Image
            src={previewImage}
            style={{ display: "none" }}
            preview={{ visible: true, onVisibleChange: (v) => { if (!v) setPreviewImage(null); } }}
          />
        )}

        {/* Image -> copy modal */}
        <Modal
          title="从图片写文案"
          open={imageWriterOpen}
          onCancel={() => setImageWriterOpen(false)}
          width={640}
          footer={
            <Space>
              <Button onClick={() => setImageWriterOpen(false)}>取消</Button>
              <Button
                type="primary"
                loading={writerGenerating}
                disabled={!writerFiles.length}
                onClick={() => void handleGenerateFromImages()}
              >
                生成文案
              </Button>
            </Space>
          }
        >
          <Upload.Dragger
            accept="image/*"
            multiple
            showUploadList={false}
            beforeUpload={(file) => handleWriterUpload(file as File)}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text" style={{ fontSize: 13 }}>点击或拖拽上传图片（最多 9 张）</p>
            <p className="ant-upload-hint" style={{ fontSize: 12 }}>
              AI 会先理解图片内容，再按账号的创作 Skill 写文案，图片会自动挂到新草稿
            </p>
          </Upload.Dragger>

          {writerPreviews.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
              {writerPreviews.map((src, index) => (
                <div key={src} style={{ position: "relative", width: 72, height: 72 }}>
                  <img
                    src={src}
                    style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 8 }}
                  />
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    style={{ position: "absolute", top: -8, right: -8, background: token.colorBgElevated, borderRadius: "50%" }}
                    onClick={() => removeWriterImage(index)}
                  />
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              可选：补一句图片说明（视觉模型不可用时必填）
            </Text>
            <TextArea
              rows={2}
              value={writerHint}
              onChange={(event) => setWriterHint(event.target.value)}
              placeholder="例如：这是我在家做的 5 分钟早餐，酸奶燕麦杯"
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              绑定账号：{accounts.find((account) => account.id === draftAccountId)?.nickname || "未绑定（可先在编辑器选择）"}
            </Text>
          </div>
        </Modal>

        {/* Note preview modal */}
        <Modal
          title="笔记预览"
          open={previewOpen}
          onCancel={() => setPreviewOpen(false)}
          width={560}
          footer={
            <Space>
              <Button loading={scoringKind === "title"} onClick={() => void handlePreviewScoreTitle()}>
                标题打分
              </Button>
              <Button loading={scoringKind === "note"} onClick={() => void handlePreviewScoreNote()}>
                笔记体检
              </Button>
              <Button type="primary" onClick={() => setPreviewOpen(false)}>关闭</Button>
            </Space>
          }
        >
          <div style={{ background: token.colorBgLayout, borderRadius: 12, padding: 16, maxHeight: "66vh", overflowY: "auto" }}>
            <Space align="center" style={{ marginBottom: 12 }}>
              <Avatar size={32}>
                {accounts.find((account) => account.id === draftAccountId)?.nickname?.[0] || "我"}
              </Avatar>
              <div>
                <Text strong style={{ display: "block", fontSize: 13 }}>
                  {accounts.find((account) => account.id === draftAccountId)?.nickname || "未绑定账号"}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>刚刚</Text>
              </div>
            </Space>

            {imageAssets.length > 0 ? (
              <>
                <img
                  src={imageAssetUrl(imageAssets[0])}
                  style={{ width: "100%", borderRadius: 8, display: "block" }}
                />
                {imageAssets.length > 1 && (
                  <div style={{ display: "flex", gap: 6, marginTop: 8, overflowX: "auto" }}>
                    {imageAssets.slice(1).map((asset) => (
                      <img
                        key={asset.id}
                        src={imageAssetUrl(asset)}
                        style={{ width: 64, height: 64, objectFit: "cover", borderRadius: 8, flexShrink: 0 }}
                      />
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div style={{ height: 160, borderRadius: 8, background: token.colorFillQuaternary, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Text type="secondary">还没有图片素材</Text>
              </div>
            )}

            <Title level={4} style={{ margin: "12px 0 8px", fontSize: 18 }}>
              {title || "未填写标题"}
            </Title>
            <Paragraph style={{ whiteSpace: "pre-wrap", color: token.colorText, fontSize: 13, marginBottom: 8 }}>
              {body || "还没有正文。"}
            </Paragraph>
            {draftTags.length > 0 && (
              <Space size={4} wrap>
                {draftTags.map((tag) => (
                  <Text key={tag.name} style={{ color: token.colorPrimary, fontSize: 12 }}>#{tag.name}</Text>
                ))}
              </Space>
            )}
            <Divider style={{ margin: "12px 0" }} />
            <Space size={16} style={{ color: token.colorTextTertiary, fontSize: 12 }}>
              <span><HeartOutlined /> 0</span>
              <span><StarOutlined /> 0</span>
              <span><MessageOutlined /> 0</span>
            </Space>
          </div>
          {previewScore && (
            <div style={{ marginTop: 12 }}>
              <ScoreCard result={previewScore} onClose={() => setPreviewScore(null)} />
            </div>
          )}
        </Modal>
      </Row>
      </>
    );
  }

  // ---- Generate mode: centered card ----
  function renderGenerateMode() {
    const activeTemplate = templates.find((item) => item.id === templateId);
    const isPositional = activeTemplate?.payload?.kind === "positional";
    return (
      <div style={{ maxWidth: 640, margin: "0 auto" }}>
        <Card title="AI 笔记生成">
          <Form layout="vertical">
            <Form.Item label="选题" required>
              <Input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="例如：通勤低卡早餐怎么搭配"
              />
            </Form.Item>
            <Form.Item label="结构模板（可选）">
              <Select
                allowClear
                value={templateId}
                onChange={(value) => {
                  const next = value ?? null;
                  setTemplateId(next);
                  const nextTemplate = templates.find((item) => item.id === next);
                  if (nextTemplate?.payload?.kind !== "positional") {
                    setEnhanceMiddle(false);
                  }
                }}
                placeholder={templates.length ? "套用某个结构模板的标题公式与段落顺序" : "暂无模板，可先去「结构模板」创建"}
                options={activeTemplates.map((item) => ({
                  value: item.id,
                  label: `${item.name}（${item.payload?.source_count ?? 0} 篇）`,
                }))}
                notFoundContent="暂无结构模板"
              />
              <TemplatePreview template={activeTemplate} />
            </Form.Item>
            {isPositional ? (
              <Form.Item
                label="中段深度增强（实验）"
                extra="实验层，不是赛道统计：Excel 语料里备选方案只占 2%、适用条件 9%。打开后会在步骤之外补一句原理、一句适用条件和一个备选方法；目前只验证过单篇，未证明稳定提升。"
              >
                <Space>
                  <Switch checked={enhanceMiddle} onChange={setEnhanceMiddle} />
                  <Text type="secondary">
                    {enhanceMiddle ? "生成时补中段深度（实验）" : "只按结构模板写"}
                  </Text>
                </Space>
              </Form.Item>
            ) : null}
            <Form.Item label="参考材料">
              <TextArea
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="竞品笔记、卖点、评论洞察或人群信息"
                rows={6}
              />
            </Form.Item>
            <Form.Item label="AI 指令">
              <Input
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="保留事实，增强小红书种草感，语气自然。"
              />
            </Form.Item>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              onClick={handleGenerateNote}
              loading={isGenerating}
              block
            >
              生成草稿
            </Button>
          </Form>
        </Card>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <PageHeader
        eyebrow="草稿工坊"
        title="草稿工坊"
        description="管理草稿、编辑内容和素材、AI 改写润色，生成结果送入发布中心。"
        action={
          <Button icon={<ReloadOutlined />} onClick={() => confirmDiscard(() => void loadDrafts())} loading={isLoading}>
            刷新草稿
          </Button>
        }
      />

      {publishIntent ? (
        <Alert
          type="info"
          showIcon
          message="首次发布：已自动选中第一篇草稿"
          description="先完成发布就绪检查；缺账号或素材时按提示补齐，再点「送入发布中心」。"
        />
      ) : null}

      {missingMediaCount > 0 ? (
        <Alert
          type="warning"
          showIcon
          message={`${missingMediaCount} 篇草稿缺素材，发布会卡在预检。`}
          description="在草稿队列行内点「去配图」；从这里进入会带上当前草稿，生成后可直接写入草稿。"
          action={
            <Button
              size="small"
              onClick={() => {
                if (!selectedDraftId) {
                  antMessage.warning("先在草稿队列里选一篇草稿，再点「去配图」。");
                  return;
                }
                navigate(`/platforms/xhs/write/visual/images?draft_id=${selectedDraftId}`);
              }}
            >
              去配图
            </Button>
          }
        />
      ) : null}

      <div>
        <Button
          type="link"
          size="small"
          style={{ paddingInline: 0 }}
          onClick={() => setBatchOpen((value) => !value)}
        >
          {batchOpen ? "收起批量生成" : "批量生成（多账号版本 / 按关键词定时生成）"}
        </Button>
        {batchOpen ? (
          <Card size="small" style={{ marginTop: 4 }}>
            <Space wrap>
              <Link to="/platforms/xhs/write/batch?mode=matrix">
                <Button size="small">多账号版本</Button>
              </Link>
              <Link to="/platforms/xhs/write/batch?mode=auto">
                <Button size="small">按关键词定时生成</Button>
              </Link>
              <Text type="secondary" style={{ fontSize: 12 }}>
                只生成草稿，不自动发布；高风险能力需先在设置 → 风险控制中开启。
              </Text>
            </Space>
          </Card>
        ) : null}
      </div>

      <Segmented
        value={activeMode}
        onChange={(val) => setActiveMode(val as AiContentMode)}
        options={segmentedOptions}
        block
        style={{ marginBottom: 8 }}
      />

      {error && (
        <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />
      )}

      {activeMode === "rewrite" ? renderRewriteMode() : renderGenerateMode()}

      <NextStepBar
        description="草稿写完后，先去发布队列做预检；没有选题就先回选题库。"
        actions={[
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs", primary: true },
          { label: "去找选题", to: "/platforms/xhs/plan" },
          { label: "去样本库", to: "/platforms/xhs/assets/library" },
        ]}
      />
    </div>
  );
}
