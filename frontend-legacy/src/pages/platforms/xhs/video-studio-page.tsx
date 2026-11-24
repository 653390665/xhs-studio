import {
  CopyOutlined,
  DeleteOutlined,
  ReloadOutlined,
  UploadOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Popconfirm,
  Row,
  Space,
  Spin,
  Typography,
  Upload,
  message,
} from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import { deleteUserVideo, fetchUserVideos, uploadAssetFile } from "../../../lib/api";
import type { UserVideoFile } from "../../../lib/api";

const { Text, Paragraph } = Typography;

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function XhsVideoStudioPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [videos, setVideos] = useState<UserVideoFile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadVideos() {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchUserVideos();
      setVideos(data.items ?? []);
    } catch {
      setError("视频列表加载失败，请确认后端已启动。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadVideos();
  }, []);

  async function handleUpload(file: File): Promise<false> {
    setIsUploading(true);
    setError(null);
    try {
      const uploaded = await uploadAssetFile(file);
      if (uploaded.asset_type !== "video") {
        setError("只支持视频文件（mp4 / mov / avi / mkv）。");
      } else {
        message.success(`已上传：${file.name}`);
        await loadVideos();
      }
    } catch {
      setError("上传失败：视频需 ≤100MB，且格式为 mp4 / mov / avi / mkv。");
    } finally {
      setIsUploading(false);
    }
    return false;
  }

  async function handleDelete(fileName: string) {
    setError(null);
    try {
      await deleteUserVideo(fileName);
      setVideos((current) => current.filter((item) => item.file_name !== fileName));
      message.success("已删除");
    } catch {
      setError("删除失败，请稍后重试。");
    }
  }

  async function handleCopy(url: string) {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${url}`);
      message.success("链接已复制");
    } catch {
      message.warning("复制失败，请手动右键复制");
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {!embedded ? (
        <PageHeader
          eyebrow="视频素材"
          title="视频素材"
          description="仅本地素材管理（≤100MB，mp4/mov/avi/mkv）：不剪辑、不转码、不自动上传，也不会创建发布任务。"
          action={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => void loadVideos()} loading={isLoading}>
                刷新
              </Button>
              <Upload
                accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,.mp4,.mov,.avi,.mkv"
                showUploadList={false}
                beforeUpload={(file) => {
                  void handleUpload(file);
                  return false;
                }}
              >
                <Button type="primary" icon={<UploadOutlined />} loading={isUploading}>
                  上传视频
                </Button>
              </Upload>
            </Space>
          }
        />
      ) : null}

      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(null)} />}

      <Card
        title={`视频列表 ${videos.length ? `· ${videos.length} 个` : ""}`}
        extra={
          embedded ? (
            <Upload
              accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,.mp4,.mov,.avi,.mkv"
              showUploadList={false}
              beforeUpload={(file) => {
                void handleUpload(file);
                return false;
              }}
            >
              <Button size="small" type="primary" icon={<UploadOutlined />} loading={isUploading}>
                上传视频
              </Button>
            </Upload>
          ) : undefined
        }
      >
        {isLoading ? (
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin />
          </div>
        ) : videos.length === 0 ? (
          <Empty
            image={<VideoCameraOutlined style={{ fontSize: 56, color: "#8c8c8c" }} />}
            imageStyle={{ height: 70 }}
            description={
              <div>
                <Text strong style={{ display: "block", marginBottom: 6 }}>还没有视频素材</Text>
                <Text type="secondary">点右上角「上传视频」开始，上传后可在此预览和管理。</Text>
              </div>
            }
          />
        ) : (
          <Row gutter={[16, 16]}>
            {videos.map((video) => (
              <Col xs={24} sm={12} lg={8} xl={6} key={video.file_name}>
                <Card
                  size="small"
                  cover={
                    <video
                      src={video.url}
                      controls
                      preload="metadata"
                      style={{ width: "100%", aspectRatio: "16/9", background: "#000", display: "block" }}
                    />
                  }
                  actions={[
                    <Button key="copy" type="text" icon={<CopyOutlined />} onClick={() => void handleCopy(video.url ?? "")}>
                      链接
                    </Button>,
                    <Popconfirm
                      key="delete"
                      title="删除这个视频？"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => void handleDelete(video.file_name)}
                    >
                      <Button type="text" danger icon={<DeleteOutlined />}>删除</Button>
                    </Popconfirm>,
                  ]}
                >
                  <Text ellipsis style={{ fontSize: 12, display: "block" }} title={video.file_name}>
                    {video.file_name}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{formatSize(video.size ?? 0)}</Text>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      <Paragraph type="secondary" style={{ fontSize: 12, margin: 0 }}>
        说明：这里只做本地素材管理，不会上传到小红书，也不会创建发布任务。发布请从草稿工坊送入发布中心；剪辑/转码/提文案等能力尚未接入。
      </Paragraph>

      <NextStepBar
        description="视频素材准备完成后回草稿工坊配图，或直接去发布队列确认预检。"
        actions={[
          { label: "回草稿配图", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs" },
        ]}
      />
    </div>
  );
}
