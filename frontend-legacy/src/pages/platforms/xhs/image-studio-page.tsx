import {
  DeleteOutlined,
  FileImageOutlined,
  LinkOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  StarOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Image,
  Input,
  InputNumber,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
  Upload,
  theme,
  message,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  addDraftAsset,
  deleteGeneratedImageAsset,
  deleteUserImage,
  describeImageWithAi,
  fetchGeneratedImageAssets,
  fetchUserImages,
  generateImageWithAi,
  uploadAssetFile,
} from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type { GenerateImageResult, GeneratedImageAsset, UserImageFile } from "../../../types";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

function isRenderableImage(value: string): boolean {
  return (
    value.startsWith("http://") ||
    value.startsWith("https://") ||
    value.startsWith("data:image/") ||
    value.startsWith("/api/")
  );
}

type AssetFilter = "all" | "ai" | "card" | "upload";

type UnifiedAsset = {
  key: string;
  kind: "ai" | "card" | "upload";
  url: string;
  title: string;
  meta: string;
  createdAt?: string;
  onDelete: () => Promise<void>;
};

const IMAGE_PRESETS = [
  { key: "cover", label: "小红书封面 3:4", size: "1080x1440", style: "clean editorial cover, one clear subject, no text" },
  { key: "square", label: "方图 1:1", size: "1080x1080", style: "clean square social image, one clear subject" },
  { key: "wide", label: "正文配图 16:9", size: "1280x720", style: "horizontal illustration, clean composition" },
  { key: "card", label: "卡片背景 3:4", size: "1080x1440", style: "minimal background, soft gradient, no text, no logo" },
];

export function XhsImageStudioPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { token } = theme.useToken();
  const [assetFilter, setAssetFilter] = useState<AssetFilter>("all");
  const [assets, setAssets] = useState<GeneratedImageAsset[]>([]);
  const [userImages, setUserImages] = useState<UserImageFile[]>([]);
  const [prompt, setPrompt] = useState("");
  const [presetKey, setPresetKey] = useState("cover");
  const [batchCount, setBatchCount] = useState(1);
  const [referenceImages, setReferenceImages] = useState<string[]>([]);
  const [imageUrl, setImageUrl] = useState("");
  const [description, setDescription] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDescribing, setIsDescribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refPickerOpen, setRefPickerOpen] = useState(false);
  const [saveToAssets, setSaveToAssets] = useState(true);
  const [generatedPreview, setGeneratedPreview] = useState<string | null>(null);
  const [attachingDraft, setAttachingDraft] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const appliedQuery = useRef(false);
  const [prefillDraftId, setPrefillDraftId] = useState<number | null>(null);

  // For the reference picker modal: which callback mode
  const [pickerMode, setPickerMode] = useState<"reference" | "describe">(
    "reference",
  );
  const [pickerUrlInput, setPickerUrlInput] = useState("");

  async function loadAssets() {
    setIsLoading(true);
    setError(null);
    try {
      const [aiResult, userResult] = await Promise.all([
        fetchGeneratedImageAssets(),
        fetchUserImages(),
      ]);
      setAssets(aiResult.items);
      setUserImages(userResult.items);
    } catch {
      setError("图片资产加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (appliedQuery.current) return;
    appliedQuery.current = true;
    const incomingPrompt = searchParams.get("prompt") || "";
    const incomingPreset = searchParams.get("preset") || "";
    const incomingDraft = Number(searchParams.get("draft_id") || "");
    let touched = false;
    if (incomingPrompt) {
      setPrompt(String(incomingPrompt));
      touched = true;
    }
    if (incomingPreset && IMAGE_PRESETS.some((item) => item.key === incomingPreset)) {
      setPresetKey(incomingPreset);
      touched = true;
    }
    if (Number.isFinite(incomingDraft) && incomingDraft > 0) {
      setPrefillDraftId(incomingDraft);
      touched = true;
    }
    if (touched) {
      const next = new URLSearchParams(searchParams);
      next.delete("prompt");
      next.delete("preset");
      next.delete("draft_id");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  async function handleGenerate() {
    if (!prompt.trim()) {
      setError("请填写提示词。");
      return;
    }
    const preset = IMAGE_PRESETS.find((item) => item.key === presetKey) || IMAGE_PRESETS[0];
    const count = Math.max(1, Math.min(4, batchCount));
    setIsGenerating(true);
    setError(null);
    setGeneratedPreview(null);
    try {
      const results = await Promise.allSettled(
        Array.from({ length: count }, (_, index) =>
          generateImageWithAi({
            prompt: `${preset.style}。${prompt.trim()}${count > 1 ? `。变体 ${index + 1}` : ""}`,
            reference_images: referenceImages.length > 0 ? referenceImages : undefined,
            save_to_assets: saveToAssets,
            draft_id: prefillDraftId ?? undefined,
            size: preset.size,
          }),
        ),
      );
      const succeeded = results
        .filter((item): item is PromiseFulfilledResult<GenerateImageResult> => item.status === "fulfilled")
        .map((item) => item.value);
      const failed = results.length - succeeded.length;
      if (succeeded.length === 0) {
        throw new Error("all failed");
      }
      setGeneratedPreview(succeeded[0].url);
      const newAssets = succeeded.map((item) => item.asset).filter((asset): asset is NonNullable<typeof asset> => Boolean(asset));
      if (newAssets.length) {
        setAssets((prev) => [...newAssets, ...prev]);
      }
      const summary = `生成完成：成功 ${succeeded.length} 张${failed ? `，失败 ${failed} 张` : ""}。`;
      if (failed > 0) message.warning(summary);
      else message.success(summary);
    } catch {
      setError("AI 图片生成失败，请确认已配置图片生成模型。");
    } finally {
      setIsGenerating(false);
    }
  }

  async function attachGeneratedToDraft() {
    if (!generatedPreview) return;
    if (!prefillDraftId) {
      message.warning("请从草稿工坊的「去配图」进入，才能把图片写入草稿。");
      return;
    }
    setAttachingDraft(true);
    try {
      await addDraftAsset(prefillDraftId, {
        asset_type: "image",
        url: generatedPreview,
      });
      message.success(`已写入草稿 #${prefillDraftId}，回草稿后记得重新检查发布条件。`);
    } catch {
      message.error("写入草稿失败，请重试。");
    } finally {
      setAttachingDraft(false);
    }
  }

  async function handleDescribeImage() {
    if (!imageUrl.trim()) {
      setError("请先填写图片 URL。");
      return;
    }
    setIsDescribing(true);
    setError(null);
    try {
      const result = await describeImageWithAi({
        image_url: imageUrl.trim(),
        instruction: "提炼这张图片适合小红书发布的卖点、风格和标题方向。",
      });
      setDescription(result.text ?? "");
      message.success("图片描述已生成。");
    } catch {
      setError("图片描述失败，请确认已配置支持视觉理解的图片模型。");
    } finally {
      setIsDescribing(false);
    }
  }

  function openRefPicker(mode: "reference" | "describe") {
    setPickerMode(mode);
    setPickerUrlInput("");
    setRefPickerOpen(true);
  }

  function handlePickerSelect(url: string) {
    if (pickerMode === "reference") {
      setReferenceImages((prev) =>
        prev.includes(url) ? prev : [...prev, url],
      );
    } else {
      setImageUrl(url);
    }
    setRefPickerOpen(false);
  }

  function handlePickerUrlAdd() {
    const trimmed = pickerUrlInput.trim();
    if (!trimmed) return;
    handlePickerSelect(trimmed);
  }

  async function handleUploadFile(file: File) {
    try {
      const uploaded = await uploadAssetFile(file);
      const newItem: UserImageFile = {
        file_name: uploaded.file_name,
        url: uploaded.download_url,
        size: uploaded.size ?? 0,
      };
      setUserImages((prev) => [newItem, ...prev]);
    } catch {
      setError("文件上传失败。");
    }
    return false; // prevent antd auto-upload
  }

  useEffect(() => {
    void loadAssets();
  }, []);

  const unifiedAssets: UnifiedAsset[] = [
    ...userImages.map((img) => ({
      key: `upload-${img.file_name}`,
      kind: "upload" as const,
      url: img.url,
      title: img.file_name,
      meta: `${(img.size / 1024).toFixed(1)} KB`,
      onDelete: async () => {
        await deleteUserImage(img.file_name);
        setUserImages((prev) => prev.filter((item) => item.file_name !== img.file_name));
      },
    })),
    ...assets.map((asset) => ({
      key: `ai-${asset.id}`,
      kind: (asset.params?.kind === "card" ? "card" : "ai") as "ai" | "card",
      url: asset.file_path,
      title: asset.prompt || "未命名素材",
      meta: asset.model_name || "image",
      createdAt: asset.created_at,
      onDelete: async () => {
        await deleteGeneratedImageAsset(asset.id);
        setAssets((prev) => prev.filter((item) => item.id !== asset.id));
      },
    })),
  ];
  const filteredAssets =
    assetFilter === "all" ? unifiedAssets : unifiedAssets.filter((item) => item.kind === assetFilter);
  const assetCounts = {
    all: unifiedAssets.length,
    ai: unifiedAssets.filter((item) => item.kind === "ai").length,
    card: unifiedAssets.filter((item) => item.kind === "card").length,
    upload: unifiedAssets.filter((item) => item.kind === "upload").length,
  };

  return (
    <div>
      {embedded ? (
        <Row justify="end" style={{ marginBottom: 12 }}>
          <Button icon={<ReloadOutlined />} onClick={loadAssets} loading={isLoading}>
            刷新素材
          </Button>
        </Row>
      ) : (
        <PageHeader
          eyebrow="图片素材"
          title="图片素材"
          description="AI 图片生成、图片描述、上传与卡片产出，统一沉淀为可复用素材；发布交接只到草稿。"
          action={
            <Button
              icon={<ReloadOutlined />}
              onClick={loadAssets}
              loading={isLoading}
            >
              刷新素材
            </Button>
          }
        />
      )}

      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          closable
          onClose={() => setError(null)}
          style={{ marginBottom: 16 }}
        />
      )}
      {prefillDraftId ? (
        <Alert
          type="info"
          showIcon
          closable
          onClose={() => setPrefillDraftId(null)}
          message={`已从草稿 #${prefillDraftId} 的视觉简报带入提示词`}
          description="生成完成后会保存到 AI 资产；回到草稿页，从图片素材把图片加入这篇笔记。"
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {/* ---- Top Row: Two tool cards ---- */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {/* Left Card: AI Image Generation */}
        <Col xs={24} md={14}>
          <Card
            title={
              <Space>
                <StarOutlined /> AI 图片生成
              </Space>
            }
            extra={
              <Text type="secondary" style={{ fontSize: 11 }}>
                需配置图片生成模型（如 gpt-image-2、豆包 Seedream）
              </Text>
            }
          >
            <Row gutter={8} style={{ marginBottom: 10 }}>
              <Col span={14}>
                <Text type="secondary" style={{ fontSize: 12 }}>尺寸 / 场景预设</Text>
                <Select
                  value={presetKey}
                  onChange={setPresetKey}
                  style={{ width: "100%" }}
                  options={IMAGE_PRESETS.map((item) => ({ value: item.key, label: `${item.label} · ${item.size}` }))}
                />
              </Col>
              <Col span={10}>
                <Text type="secondary" style={{ fontSize: 12 }}>批量数量</Text>
                <InputNumber
                  min={1}
                  max={4}
                  value={batchCount}
                  onChange={(value) => setBatchCount(Number(value ?? 1))}
                  style={{ width: "100%" }}
                />
              </Col>
            </Row>
            <TextArea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="充满活力的特写编辑肖像，模特眼神犀利，头戴雕塑感帽子，色彩拼接丰富，具有 Vogue 杂志封面的美学风格..."
              rows={4}
              disabled={isGenerating}
              style={{ marginBottom: 12 }}
            />

            {/* Reference images */}
            <div style={{ marginBottom: 12 }}>
              <Text
                type="secondary"
                style={{ fontSize: 12, marginBottom: 6, display: "block" }}
              >
                参考图
              </Text>
              <Space size={8} wrap>
                {referenceImages.map((url, idx) => (
                  <div
                    key={idx}
                    style={{
                      position: "relative",
                      width: 60,
                      height: 60,
                      borderRadius: 8,
                      overflow: "hidden",
                      border: `1px solid ${token.colorBorder}`,
                    }}
                  >
                    {isRenderableImage(url) ? (
                      <img
                        src={url}
                        alt={`ref-${idx}`}
                        style={{
                          width: 60,
                          height: 60,
                          objectFit: "cover",
                        }}
                      />
                    ) : (
                      <div
                        style={{
                          width: 60,
                          height: 60,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          background: token.colorFillQuaternary,
                        }}
                      >
                        <PictureOutlined style={{ fontSize: 20, color: token.colorTextTertiary }} />
                      </div>
                    )}
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() =>
                        setReferenceImages((prev) =>
                          prev.filter((_, i) => i !== idx),
                        )
                      }
                      style={{
                        position: "absolute",
                        top: 0,
                        right: 0,
                        width: 18,
                        height: 18,
                        padding: 0,
                        minWidth: 18,
                        borderRadius: "0 4px 0 4px",
                        background: "rgba(0,0,0,0.6)",
                      }}
                    />
                  </div>
                ))}
                {/* Add placeholder */}
                <div
                  onClick={() => openRefPicker("reference")}
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
            </div>

            {/* Controls row */}
            <Row
              justify="space-between"
              align="middle"
              style={{ marginBottom: 12 }}
            >
              <Col>
                <Checkbox
                  checked={saveToAssets}
                  onChange={(e) => setSaveToAssets(e.target.checked)}
                >
                  保存到图片素材
                </Checkbox>
              </Col>
              <Col>
                <Space>
                  <Button
                    onClick={() => { setPrompt(String("")); setReferenceImages([]); setGeneratedPreview(null); setSaveToAssets(true); }}
                    disabled={isGenerating}
                  >
                    重置
                  </Button>
                  <Button
                    type="primary"
                    icon={<RobotOutlined />}
                    onClick={handleGenerate}
                    loading={isGenerating}
                  >
                    {batchCount > 1 ? `生成 ${batchCount} 张` : "生成"}
                  </Button>
                </Space>
              </Col>
            </Row>

            {/* Generated result */}
            {generatedPreview && (
              <div style={{ marginTop: 8 }}>
                <Text
                  type="secondary"
                  style={{ fontSize: 12, marginBottom: 6, display: "block" }}
                >
                  生成结果
                </Text>
                <div
                  style={{
                    background: token.colorFillQuaternary,
                    borderRadius: 8,
                    padding: 8,
                    textAlign: "center",
                  }}
                >
                  <Image
                    src={generatedPreview}
                    alt="generated"
                    style={{ maxHeight: 240, objectFit: "contain" }}
                  />
                  {!saveToAssets && (
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        // Re-generate with save flag
                        setSaveToAssets(true);
                        message.info("下次生成将自动保存到 AI 资产。");
                      }}
                      style={{ marginTop: 8 }}
                    >
                      保存到 AI 资产
                    </Button>
                  )}
                  {prefillDraftId ? (
                    <Button
                      size="small"
                      type="primary"
                      loading={attachingDraft}
                      onClick={() => void attachGeneratedToDraft()}
                      style={{ marginTop: 8, marginLeft: saveToAssets ? 0 : 8 }}
                    >
                      写入草稿 #{prefillDraftId}
                    </Button>
                  ) : null}
                </div>
              </div>
            )}
          </Card>
        </Col>

        {/* Right Card: Image Description */}
        <Col xs={24} md={10}>
          <Card
            title={
              <Space>
                <FileImageOutlined /> 图片描述
              </Space>
            }
            extra={
              <Text type="secondary" style={{ fontSize: 11 }}>
                需配置多模态模型（如 GPT-4o）
              </Text>
            }
          >
            <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
              <Input
                value={imageUrl}
                onChange={(e) => setImageUrl(e.target.value)}
                placeholder="图片 URL"
                disabled={isGenerating}
              />
              <Button
                icon={<PictureOutlined />}
                onClick={() => openRefPicker("describe")}
              >
                从资产选择
              </Button>
            </Space.Compact>
            <Button
              onClick={handleDescribeImage}
              loading={isDescribing}
              block
              style={{ marginBottom: 12 }}
            >
              生成描述
            </Button>
            {description && (
              <Paragraph
                style={{
                  background: token.colorFillSecondary,
                  padding: 12,
                  borderRadius: 8,
                  fontSize: 13,
                  margin: 0,
                }}
              >
                {description}
              </Paragraph>
            )}
          </Card>
        </Col>
      </Row>

      {/* ---- Bottom: unified asset library ---- */}
      <Card
        title="素材列表"
        extra={
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {filteredAssets.length} 个
            </Text>
            <Upload
              accept="image/*"
              showUploadList={false}
              beforeUpload={(file) => {
                void handleUploadFile(file);
                return false;
              }}
            >
              <Button size="small" icon={<UploadOutlined />}>上传图片</Button>
            </Upload>
          </Space>
        }
        style={{ marginTop: 8 }}
      >
        <Segmented
          size="small"
          value={assetFilter}
          onChange={(value) => setAssetFilter(value as AssetFilter)}
          options={[
            { value: "all", label: `全部 ${assetCounts.all}` },
            { value: "ai", label: `AI ${assetCounts.ai}` },
            { value: "card", label: `卡片 ${assetCounts.card}` },
            { value: "upload", label: `上传 ${assetCounts.upload}` },
          ]}
          style={{ marginBottom: 16 }}
        />
        {isLoading ? (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin tip="正在加载素材..." />
          </div>
        ) : filteredAssets.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={assetFilter === "all" ? "暂无素材，生成或上传后会显示在这里。" : "这个分类下还没有素材。"}
            style={{ padding: 32 }}
          />
        ) : (
          <Row gutter={[12, 12]}>
            {filteredAssets.map((item) => (
              <Col xs={12} sm={8} md={6} key={item.key}>
                <Card size="small" hoverable styles={{ body: { padding: 8 } }}>
                  <div
                    style={{
                      height: 120,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      marginBottom: 6,
                      overflow: "hidden",
                      borderRadius: 8,
                      background: token.colorFillQuaternary,
                    }}
                  >
                    {isRenderableImage(item.url) ? (
                      <Image alt={item.title} src={item.url} style={{ maxHeight: 120, objectFit: "contain" }} />
                    ) : (
                      <PictureOutlined style={{ fontSize: 28, color: token.colorTextTertiary }} />
                    )}
                  </div>
                  <Text strong ellipsis style={{ fontSize: 12, display: "block" }}>{item.title}</Text>
                  <div style={{ marginTop: 4 }}>
                    {item.kind === "card" ? (
                      <Tag color="purple" style={{ fontSize: 10, padding: "0 4px", margin: 0 }}>卡片</Tag>
                    ) : item.kind === "upload" ? (
                      <Tag color="blue" style={{ fontSize: 10, padding: "0 4px", margin: 0 }}>上传</Tag>
                    ) : (
                      <Tag style={{ fontSize: 10, padding: "0 4px", margin: 0 }}>AI</Tag>
                    )}
                    <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>{item.meta}</Text>
                  </div>
                  {item.createdAt ? (
                    <Text type="secondary" style={{ fontSize: 10, display: "block", marginTop: 2 }}>
                      {formatShanghaiTime(item.createdAt)}
                    </Text>
                  ) : null}
                  <Button
                    type="text" danger size="small" icon={<DeleteOutlined />}
                    onClick={() => void item.onDelete()}
                    style={{ width: "100%", marginTop: 4 }}
                  >
                    删除
                  </Button>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* ---- Reference Image Picker Modal ---- */}
      <Modal
        title="选择图片"
        open={refPickerOpen}
        onCancel={() => setRefPickerOpen(false)}
        footer={null}
        width={640}
        destroyOnClose
      >
        <Tabs
          defaultActiveKey="user_images"
          items={[
            {
              key: "user_images",
              label: (
                <Space>
                  <PictureOutlined /> 本地上传
                </Space>
              ),
              children:
                userImages.length === 0 ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="暂无本地上传的图片。"
                    style={{ padding: 24 }}
                  />
                ) : (
                  <Row gutter={[8, 8]}>
                    {userImages.map((img) => (
                      <Col span={6} key={img.file_name}>
                        <div
                          onClick={() => handlePickerSelect(img.url)}
                          style={{
                            cursor: "pointer",
                            borderRadius: 8,
                            overflow: "hidden",
                            border: `1px solid ${token.colorBorder}`,
                            height: 80,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            background: token.colorFillQuaternary,
                          }}
                        >
                          <img
                            src={img.url}
                            alt={img.file_name}
                            style={{
                              maxHeight: 80,
                              maxWidth: "100%",
                              objectFit: "contain",
                            }}
                          />
                        </div>
                      </Col>
                    ))}
                  </Row>
                ),
            },
            {
              key: "ai_assets",
              label: (
                <Space>
                  <StarOutlined /> 图片素材
                </Space>
              ),
              children:
                assets.length === 0 ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="暂无素材。"
                    style={{ padding: 24 }}
                  />
                ) : (
                  <Row gutter={[8, 8]}>
                    {assets.map((asset) => (
                      <Col span={6} key={asset.id}>
                        <div
                          onClick={() => handlePickerSelect(asset.file_path)}
                          style={{
                            cursor: "pointer",
                            borderRadius: 8,
                            overflow: "hidden",
                            border: `1px solid ${token.colorBorder}`,
                            height: 80,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            background: token.colorFillQuaternary,
                          }}
                        >
                          {isRenderableImage(asset.file_path) ? (
                            <img
                              src={asset.file_path}
                              alt={asset.prompt}
                              style={{
                                maxHeight: 80,
                                maxWidth: "100%",
                                objectFit: "contain",
                              }}
                            />
                          ) : (
                            <PictureOutlined
                              style={{ fontSize: 24, color: token.colorTextTertiary }}
                            />
                          )}
                        </div>
                      </Col>
                    ))}
                  </Row>
                ),
            },
            {
              key: "url",
              label: (
                <Space>
                  <LinkOutlined /> URL
                </Space>
              ),
              children: (
                <Space.Compact style={{ width: "100%" }}>
                  <Input
                    value={pickerUrlInput}
                    onChange={(e) => setPickerUrlInput(e.target.value)}
                    placeholder="输入图片 URL"
                    onPressEnter={handlePickerUrlAdd}
                  />
                  <Button type="primary" onClick={handlePickerUrlAdd}>
                    添加
                  </Button>
                </Space.Compact>
              ),
            },
          ]}
        />
      </Modal>

      <NextStepBar
        description="从草稿进入时，生成后可直接「写入草稿」；否则先保存到 AI 资产，再回草稿素材库选取。"
        actions={[
          { label: "回草稿配图", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs" },
        ]}
      />
    </div>
  );
}
