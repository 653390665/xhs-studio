import {
  CommentOutlined,
  CrownOutlined,
  DatabaseOutlined,
  FireOutlined,
  HeartOutlined,
  LinkOutlined,
  PictureOutlined,
  SearchOutlined,
  StarOutlined,
  ThunderboltOutlined,
  TrophyOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Col, DatePicker, Empty, Input, Row, Segmented, Select, Space, Spin, Table, Tabs, Tag, theme, Typography } from "antd";
import type { Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchXhsHotAccounts, fetchXhsHotList, fetchXhsLowFanRanking, fetchXhsRanking, fetchXhsTrendsMeta, fetchXhsViralInsights, searchXhsTrendUsers } from "../../../lib/api";
import { formatTrend, trendColor } from "../../../lib/trend";
import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import type { XhsHotAccount, XhsHotListItem, XhsSearchNote, XhsTrendMeta, XhsTrendUser } from "../../../types";

const { Text, Paragraph } = Typography;

/** Data source is RedFox only; the PC provider has no equivalent endpoints. */
const sortOptions = [
  { value: 0, label: "相关性" },
  { value: 1, label: "最新" },
  { value: 2, label: "最热" },
];

function formatMetric(value: number | undefined): string {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num) || num <= 0) return "—";
  if (num >= 10000) return `${(num / 10000).toFixed(num >= 100000 ? 0 : 1)}w`;
  return num.toLocaleString();
}

function formatDate(note: XhsSearchNote): string {
  const ts = note.timestamp;
  const num = typeof ts === "number" ? ts : Number(ts);
  if (!Number.isFinite(num) || num <= 0) return "";
  return new Date(num > 1e12 ? num : num * 1000).toLocaleDateString("zh-CN");
}

function noteUrl(note: XhsSearchNote): string {
  return note.note_url || (note.note_id ? `https://www.xiaohongshu.com/explore/${note.note_id}` : "");
}

function NoteGrid({ notes, loading, emptyText }: { notes: XhsSearchNote[]; loading: boolean; emptyText: string }) {
  const { token } = theme.useToken();
  if (loading) {
    return <div style={{ padding: 48, textAlign: "center" }}><Spin /></div>;
  }
  if (!notes.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} style={{ marginTop: 32 }} />;
  }
  return (
    <Row gutter={[16, 16]}>
      {notes.map((note) => {
        const cover = note.cover_url || note.image_urls?.[0] || "";
        const url = noteUrl(note);
        const ratio = note.like_fan_ratio ?? 0;
        const hot = ratio >= 10;
        return (
          <Col xs={12} sm={8} md={6} lg={6} xl={4} key={`${note.note_id}-${note.title}`}>
            <Card
              hoverable
              size="small"
              style={{ overflow: "hidden" }}
              onClick={() => url && window.open(url, "_blank", "noopener")}
              cover={
                <div style={{ position: "relative", background: token.colorFillQuaternary }}>
                  {cover
                    ? <img src={cover} alt={note.title || "封面"} referrerPolicy="no-referrer" onError={(event) => { event.currentTarget.style.visibility = "hidden"; }} style={{ width: "100%", aspectRatio: "1/1", objectFit: "cover", display: "block" }} />
                    : <div style={{ width: "100%", aspectRatio: "1/1", display: "flex", alignItems: "center", justifyContent: "center", color: token.colorTextQuaternary, fontSize: 28 }}><PictureOutlined /></div>}
                  {hot && <Tag color="gold" style={{ position: "absolute", top: 8, right: 8 }} icon={<FireOutlined />}>爆款</Tag>}
                </div>
              }
            >
              <Card.Meta
                title={<Text ellipsis style={{ fontSize: 13 }}>{note.title || "未命名笔记"}</Text>}
                description={
                  <>
                    <Text type="secondary" style={{ fontSize: 12 }}>{note.author_name || "未知作者"}</Text>
                    {formatDate(note) && <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>{formatDate(note)}</Text>}
                  </>
                }
              />
              <Space size={12} style={{ marginTop: 8, fontSize: 12, color: token.colorTextTertiary, flexWrap: "wrap" }}>
                <span><HeartOutlined /> {formatMetric(note.likes)}</span>
                <span><StarOutlined /> {formatMetric(note.collects)}</span>
                <span><CommentOutlined /> {formatMetric(note.comments)}</span>
              </Space>
              <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>粉丝 {note.author_fans ? formatMetric(note.author_fans) : "—"}</Text>
                <Tag color={hot ? "gold" : "default"} style={{ marginInlineEnd: 0, fontSize: 11 }}>赞粉比 {ratio.toFixed(2)}</Tag>
              </div>
            </Card>
          </Col>
        );
      })}
    </Row>
  );
}

export function XhsTrendsPage() {
  const navigate = useNavigate();
  const [meta, setMeta] = useState<XhsTrendMeta | null>(null);
  const [metaLoading, setMetaLoading] = useState(true);
  const [category, setCategory] = useState("综合全部");
  const [rankDate, setRankDate] = useState<Dayjs | null>(null);
  const [keyword, setKeyword] = useState("");
  const [userKeyword, setUserKeyword] = useState("");
  const [userSort, setUserSort] = useState(0);
  const [insights, setInsights] = useState<{ items: XhsSearchNote[]; hot_topics: Array<Record<string, unknown>>; related: Array<{ keyword?: string; articleCount?: number }> }>({ items: [], hot_topics: [], related: [] });
  const [lowFan, setLowFan] = useState<XhsSearchNote[]>([]);
  const [daily, setDaily] = useState<XhsSearchNote[]>([]);
  const [weekly, setWeekly] = useState<XhsSearchNote[]>([]);
  const [users, setUsers] = useState<XhsTrendUser[]>([]);
  const [hotAccounts, setHotAccounts] = useState<XhsHotAccount[]>([]);
  const [hotDateType, setHotDateType] = useState(1);
  const [hotList, setHotList] = useState<XhsHotListItem[]>([]);
  const [hotRange, setHotRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const categories = useMemo(() => meta?.categories ?? ["综合全部"], [meta]);
  const available = meta?.available ?? false;
  const hotListAvailable = meta?.hot_list_available ?? available;
  const hotListSource = meta?.hot_list_source ?? "none";

  useEffect(() => {
    void loadMeta();
  }, []);

  async function loadMeta(refresh = false) {
    setMetaLoading(true);
    setError(null);
    try {
      const loaded = await fetchXhsTrendsMeta({ refresh });
      setMeta(loaded);
      // Unavailable is expected when RedFox is not configured or out of points:
      // the banner below explains it, so don't duplicate it as a request error.
    } catch {
      setError("读取数据源状态失败，请确认后端已启动。");
    } finally {
      setMetaLoading(false);
    }
  }

  function setBusy(key: string, value: boolean) {
    setLoading((current) => ({ ...current, [key]: value }));
  }

  async function run<T>(key: string, task: () => Promise<T>, onDone: (result: T) => void) {
    setError(null); setNotice(null); setBusy(key, true);
    try {
      onDone(await task());
    } catch (err: unknown) {
      const e = err as { response?: { status?: number; data?: { detail?: string } }; message?: string };
      setError(e?.response?.data?.detail ? `[${e.response.status}] ${e.response.data.detail}` : `请求失败：${e?.message || "请检查后端服务"}`);
    } finally {
      setBusy(key, false);
    }
  }

  const rankDateValue = rankDate ? rankDate.format("YYYY-MM-DD") : "";

  function loadInsights() {
    void run(
      "insights",
      () => fetchXhsViralInsights({ keyword: keyword.trim(), page_size: 20 }),
      (r) => {
        setInsights({ items: r.items, hot_topics: r.hot_topics, related: r.related_searches });
        if (r.empty) setNotice("该关键词暂无洞察数据。");
      },
    );
  }

  function loadUsers() {
    void run(
      "users",
      () => searchXhsTrendUsers({ keyword: userKeyword.trim(), sort_type_choice: userSort }),
      (r) => setUsers(r.items),
    );
  }

  function loadHotAccounts() {
    void run(
      "hot-accounts",
      () => fetchXhsHotAccounts({ date_type: hotDateType, category }),
      (r) => {
        setHotAccounts(r.items);
        setNotice(
          r.empty
            ? `「${category}」在 ${r.rank_date} 没有热门账号数据，可换个分类或周期。`
            : `榜单日期：${r.rank_date}`,
        );
      },
    );
  }

  function loadRanking(period: "daily" | "weekly" | "low-fan") {
    if (period === "low-fan") {
      void run(
        "low-fan",
        () => fetchXhsLowFanRanking({ category, rank_date: rankDateValue }),
        (r) => { setLowFan(r.items); setNotice(r.empty ? `「${category}」在 ${r.rank_date} 没有榜单数据，可换个分类或日期。` : `榜单日期：${r.rank_date}`); },
      );
      return;
    }
    void run(
      period,
      () => fetchXhsRanking({ period, category, rank_date: rankDateValue }),
      (r) => {
        (period === "daily" ? setDaily : setWeekly)(r.items);
        setNotice(r.empty ? `「${category}」在 ${r.rank_date} 没有榜单数据，可换个分类或日期。` : `榜单日期：${r.rank_date}`);
      },
    );
  }

  const insightsPanel = (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="关键词，如 AIGC创业；留空则按互动数返回最热门笔记"
          style={{ width: 360 }}
          onPressEnter={loadInsights}
          disabled={!available}
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          loading={loading.insights}
          disabled={!available}
          onClick={loadInsights}
        >
          查爆款
        </Button>
        <Button
          icon={<DatabaseOutlined />}
          disabled={!keyword.trim()}
          onClick={() =>
            navigate(`/platforms/xhs/assets/collect?keyword=${encodeURIComponent(keyword.trim())}`)
          }
        >
          去搜索样本
        </Button>
      </Space>
      {(insights.related.length > 0 || insights.hot_topics.length > 0) && (
        <div style={{ marginBottom: 12 }}>
          {insights.related.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>相关搜索</Text>
              <Space wrap size={[6, 6]}>
                {insights.related.slice(0, 12).map((item, index) => (
                  <Tag key={`${item.keyword}-${index}`} style={{ cursor: "pointer" }} onClick={() => { setKeyword(String(item.keyword ?? "")); }}>
                    {String(item.keyword ?? "")}{item.articleCount ? ` · ${item.articleCount}` : ""}
                  </Tag>
                ))}
              </Space>
            </div>
          )}
          {insights.hot_topics.length > 0 && (
            <div>
              <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>热门话题</Text>
              <Space wrap size={[6, 6]}>
                {insights.hot_topics.slice(0, 12).map((topic, index) => {
                  const title = String((topic as { title?: string }).title ?? JSON.stringify(topic).slice(0, 20));
                  return (
                    <Tag
                      key={index}
                      color="blue"
                      style={{ cursor: "pointer" }}
                      onClick={() =>
                        navigate(`/platforms/xhs/assets/collect?keyword=${encodeURIComponent(title)}`)
                      }
                    >
                      {title}
                    </Tag>
                  );
                })}
              </Space>
            </div>
          )}
        </div>
      )}
      <NoteGrid notes={insights.items} loading={loading.insights} emptyText="输入关键词后点「查爆款」，这里会显示热门笔记（作者粉丝数由接口直接返回，不再额外付费补查；赞粉比仅作参考展示）。" />
    </div>
  );

  function rankingToolbar(period: "daily" | "weekly" | "low-fan") {
    const note = period === "low-fan"
      ? "黑马爆文榜：低粉高互动笔记，默认取 2 天前的榜单（接口对当天/昨天与超出 30 天的日期会返回空数据）。"
      : period === "daily"
        ? "每日爆款榜单，默认取 2 天前（榜单有约 1 天延迟）。"
        : "七日爆款笔记，默认取 7 天前。";
    return (
      <Space wrap style={{ marginBottom: 12 }}>
        <Select value={category} onChange={setCategory} options={categories.map((item) => ({ value: item, label: item }))} style={{ width: 160 }} disabled={!available} />
        <DatePicker value={rankDate} onChange={setRankDate} placeholder="榜单日期（可留空用默认）" style={{ width: 200 }} disabled={!available} />
        <Button
          type="primary"
          icon={period === "low-fan" ? <ThunderboltOutlined /> : <TrophyOutlined />}
          loading={loading[period]}
          disabled={!available}
          onClick={() => loadRanking(period)}
        >
          获取榜单
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>{note}</Text>
      </Space>
    );
  }

  const userColumns = [
    { title: "账号", dataIndex: "nickname", key: "nickname", render: (_: unknown, row: XhsTrendUser) => (
      <Space>
        {row.avatar
          ? <img src={row.avatar} alt="" referrerPolicy="no-referrer" style={{ width: 32, height: 32, borderRadius: "50%", objectFit: "cover" }} />
          : <UserOutlined />}
        <div>
          <div>{row.nickname || "未命名"}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>小红书号 {row.account_id || "—"}</Text>
        </div>
      </Space>
    ) },
    { title: "粉丝", dataIndex: "fans", key: "fans", render: (value: number) => formatMetric(value) },
    { title: "笔记", dataIndex: "notes", key: "notes" },
    { title: "获赞", dataIndex: "likes", key: "likes", render: (value: number) => formatMetric(value) },
    { title: "获藏", dataIndex: "collects", key: "collects", render: (value: number) => formatMetric(value) },
    { title: "简介", dataIndex: "desc", key: "desc", render: (value: string) => <Text type="secondary" style={{ fontSize: 12 }} ellipsis>{value || "—"}</Text> },
    {
      title: "主页",
      key: "link",
      // searchUser only returns the 小红书号; a profile URL needs the internal userId.
      render: (_: unknown, row: XhsTrendUser) => (row.user_id
        ? <Button size="small" icon={<LinkOutlined />} onClick={() => window.open(`https://www.xiaohongshu.com/user/profile/${row.user_id}`, "_blank", "noopener")}>打开</Button>
        : <Text type="secondary" style={{ fontSize: 12 }}>—</Text>),
    },
  ];

  const growthValue = (value: number) =>
    value > 0
      ? <Text style={{ color: "#49aa19", fontSize: 12 }}>+{formatMetric(value)}</Text>
      : <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;

  const hotAccountColumns = [
    { title: "#", dataIndex: "ranking", key: "ranking", width: 54 },
    {
      title: "账号",
      dataIndex: "nickname",
      key: "nickname",
      render: (_: unknown, row: XhsHotAccount) => (
        <Space>
          {row.avatar
            ? <img src={row.avatar} alt="" referrerPolicy="no-referrer" style={{ width: 32, height: 32, borderRadius: "50%", objectFit: "cover" }} />
            : <UserOutlined />}
          <div>
            <div>{row.nickname || "未命名"}</div>
            <Text type="secondary" style={{ fontSize: 12 }}>{row.category || "—"}</Text>
          </div>
        </Space>
      ),
    },
    { title: "粉丝", dataIndex: "fans", key: "fans", render: (value: number) => formatMetric(value) },
    { title: "涨粉", dataIndex: "fans_growth", key: "fans_growth", render: (value: number) => growthValue(value) },
    { title: "涨赞", dataIndex: "likes_growth", key: "likes_growth", render: (value: number) => growthValue(value) },
    { title: "涨藏", dataIndex: "collects_growth", key: "collects_growth", render: (value: number) => growthValue(value) },
    { title: "新笔记", dataIndex: "new_notes", key: "new_notes" },
    {
      title: "主页",
      key: "link",
      render: (_: unknown, row: XhsHotAccount) => (row.user_id
        ? <Button size="small" icon={<LinkOutlined />} onClick={() => window.open(`https://www.xiaohongshu.com/user/profile/${row.user_id}`, "_blank", "noopener")}>打开</Button>
        : <Text type="secondary" style={{ fontSize: 12 }}>—</Text>),
    },
  ];

  const hotAccountsPanel = (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          value={hotDateType}
          onChange={(value) => setHotDateType(Number(value))}
          options={[
            { label: "日榜", value: 1 },
            { label: "周榜", value: 2 },
            { label: "月榜", value: 3 },
          ]}
          disabled={!available}
        />
        <Select value={category} onChange={setCategory} options={categories.map((item) => ({ value: item, label: item }))} style={{ width: 160 }} disabled={!available} />
        <Button
          type="primary"
          icon={<CrownOutlined />}
          loading={loading["hot-accounts"]}
          disabled={!available}
          onClick={loadHotAccounts}
        >
          获取榜单
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          日榜默认 2 天前、周榜默认上周一、月榜默认上月 1 日；带涨粉/涨赞/涨藏增量。
        </Text>
      </Space>
      <Table
        rowKey={(row: XhsHotAccount) => `${row.ranking}-${row.nickname}`}
        dataSource={hotAccounts}
        columns={hotAccountColumns}
        loading={loading["hot-accounts"]}
        size="small"
        pagination={false}
        scroll={{ x: 860 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择周期与分类后点「获取榜单」" /> }}
      />
    </div>
  );

  function loadHotList() {
    // the free source has no date range support, only RedFox does
    const useDates = hotListSource === "redfox";
    void run(
      "hot-list",
      () => fetchXhsHotList({
        platform: 6,
        start_date: useDates && hotRange ? hotRange[0].format("YYYY-MM-DD") : "",
        end_date: useDates && hotRange ? hotRange[1].format("YYYY-MM-DD") : "",
      }),
      (r) => {
        setHotList(r.items);
        if (r.empty) {
          setNotice("该时间段没有热榜数据，可换个日期。");
        } else if (r.source === "free") {
          setNotice(`小红书热榜 · 免费源（Top ${r.total}），RedFox 不可用时自动兜底`);
        } else {
          setNotice(`小红书热榜 ${r.start_date} ~ ${r.end_date}`);
        }
      },
    );
  }

  const hotListColumns = [
    { title: "#", dataIndex: "rank", key: "rank", width: 54 },
    {
      title: "话题",
      dataIndex: "title",
      key: "title",
      render: (value: string, row: XhsHotListItem) => (row.url
        ? <a href={row.url} target="_blank" rel="noreferrer">{value}</a>
        : value),
    },
    {
      title: "热度",
      dataIndex: "hot_text",
      key: "hot_text",
      width: 110,
      render: (value: string, row: XhsHotListItem) => <Tag color="red">{value || formatMetric(row.hot_score)}</Tag>,
    },
    {
      title: "趋势",
      key: "trend",
      width: 100,
      render: (_: unknown, row: XhsHotListItem) => {
        const label = formatTrend(row.trend);
        if (!label) return <Text type="secondary" style={{ fontSize: 12 }}>新上榜</Text>;
        return <Tag color={trendColor(row.trend)} style={{ marginInlineEnd: 0 }}>{label}</Tag>;
      },
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      key: "updated_at",
      width: 180,
      render: (value: string) => <Text type="secondary" style={{ fontSize: 12 }}>{value || "—"}</Text>,
    },
  ];

  const hotListPanel = (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <DatePicker.RangePicker
          value={hotRange}
          onChange={(range) => setHotRange(range as [Dayjs, Dayjs] | null)}
          placeholder={["开始日期", "结束日期"]}
          disabled={!hotListAvailable || hotListSource !== "redfox"}
        />
        <Button
          type="primary"
          icon={<FireOutlined />}
          loading={loading["hot-list"]}
          disabled={!hotListAvailable}
          onClick={loadHotList}
        >
          获取热榜
        </Button>
        <Tag color={hotListSource === "redfox" ? "purple" : hotListSource === "free" ? "green" : "default"} style={{ marginInlineEnd: 0 }}>
          {hotListSource === "redfox"
            ? "RedFox"
            : hotListSource === "free"
              ? "免费源 60s（Top 20）"
              : "不可用"}
        </Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {hotListSource === "free"
            ? "RedFox 不可用，已自动使用免费热搜源；不支持按日期筛选。"
            : "默认昨天~今天；按次计费约 ¥0.06。"}
        </Text>
      </Space>
      <Table
        rowKey={(row: XhsHotListItem) => `${row.rank}-${row.title}`}
        dataSource={hotList}
        columns={hotListColumns}
        loading={loading["hot-list"]}
        size="small"
        pagination={false}
        scroll={{ x: 620 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="点击「获取热榜」查看小红书热搜词" /> }}
      />
    </div>
  );

  const usersPanel = (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          value={userKeyword}
          onChange={(e) => setUserKeyword(e.target.value)}
          placeholder="关键词，如 AI、通勤穿搭"
          style={{ width: 300 }}
          onPressEnter={loadUsers}
          disabled={!available}
        />
        <Select value={userSort} onChange={setUserSort} options={sortOptions} style={{ width: 120 }} disabled={!available} />
        <Button
          type="primary"
          icon={<UserOutlined />}
          loading={loading.users}
          disabled={!available || !userKeyword.trim()}
          onClick={loadUsers}
        >
          搜索账号
        </Button>
      </Space>
      <Table
        rowKey={(row: XhsTrendUser) => row.account_id || row.nickname}
        dataSource={users}
        columns={userColumns}
        loading={loading.users}
        size="small"
        pagination={false}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="输入关键词搜索小红书账号" /> }}
      />
    </div>
  );

  return (
    <div>
      <PageHeader
        eyebrow="素材"
        title="爆款榜单"
        description="看当下这个赛道什么内容在涨；样本入库后去「样本库」集中管理。"
        action={<Tag color={available ? "purple" : "default"}>{available ? "数据源：RedFox" : "未配置数据源"}</Tag>}
      />

      {!metaLoading && !available && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            meta?.reason === "insufficient_balance"
              ? "RedFox 余额为 0，该模块已暂停"
              : meta?.reason === "no_api_key"
                ? "未配置 RedFox API Key，该模块不可用"
                : "该页面需要 RedFox 数据源"
          }
          description={
            <>
              {meta?.message || "请配置 REDFOX_API_KEY 后重试。"}
              <div style={{ marginTop: 4, fontSize: 12, opacity: 0.75 }}>
                {hotListAvailable
                  ? "「小红书热榜」仍可用（已自动切换到免费源）；"
                  : "「小红书热榜」的免费源也不可用；"}
                其余功能（笔记发现、草稿、发布、爆款分析等）正常可用。
              </div>
            </>
          }
          action={
            <Button size="small" onClick={() => void loadMeta(true)} loading={metaLoading}>
              重新检测
            </Button>
          }
        />
      )}
      {error && <Alert message={error} type="error" showIcon closable style={{ marginBottom: 12 }} onClose={() => setError(null)} />}
      {notice && <Alert message={notice} type="info" showIcon closable style={{ marginBottom: 12 }} onClose={() => setNotice(null)} />}

      <Card>
        {metaLoading ? (
          <div style={{ padding: 48, textAlign: "center" }}><Spin /></div>
        ) : (
          <Tabs
            items={[
              { key: "insights", label: <span><FireOutlined /> 爆款洞察</span>, children: insightsPanel, disabled: !available },
              { key: "low-fan", label: <span><ThunderboltOutlined /> 黑马爆文榜</span>, children: <div>{rankingToolbar("low-fan")}<NoteGrid notes={lowFan} loading={loading["low-fan"]} emptyText="选择分类后点「获取榜单」。" /></div>, disabled: !available },
              { key: "daily", label: <span><TrophyOutlined /> 每日爆款</span>, children: <div>{rankingToolbar("daily")}<NoteGrid notes={daily} loading={loading.daily} emptyText="选择分类后点「获取榜单」。" /></div>, disabled: !available },
              { key: "weekly", label: <span><TrophyOutlined /> 七日爆款</span>, children: <div>{rankingToolbar("weekly")}<NoteGrid notes={weekly} loading={loading.weekly} emptyText="选择分类后点「获取榜单」。" /></div>, disabled: !available },
              { key: "hot-list", label: <span><FireOutlined /> 小红书热榜</span>, children: hotListPanel, disabled: !hotListAvailable },
              { key: "hot-accounts", label: <span><CrownOutlined /> 热门账号榜</span>, children: hotAccountsPanel, disabled: !available },
              { key: "users", label: <span><UserOutlined /> 用户搜索</span>, children: usersPanel, disabled: !available },
            ]}
          />
        )}
      </Card>

      <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
        提示：这些接口按次计费（约 ¥0.04–0.06/次），每日调用上限由后端 <code>redfox_daily_call_limit</code> 控制；榜单接口对当天/昨天与超出 30 天的日期会返回空数据，默认已用安全日期。
      </Paragraph>

      <NextStepBar
        description="榜单用于找选题和对标；下一步去选题库，或去对标分析看同阶账号。"
        actions={[
          { label: "去选题库", to: "/platforms/xhs/plan", primary: true },
          { label: "去对标分析", to: "/platforms/xhs/assets/analysis" },
        ]}
      />
    </div>
  );
}
