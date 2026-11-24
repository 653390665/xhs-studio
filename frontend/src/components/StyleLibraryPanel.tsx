/**
 * StyleLibraryPanel.tsx — 写法管理
 *
 * 后端只有一个「写法」概念（StyleProfile），来源有五种：
 *   内置（ego）/ 样本提炼 / 证据蒸馏 / 抖音蒸馏 / 工作台
 *
 * 这一页不是生成入口，是写法总账：
 *   1. 把全部写法列出来，标清来源
 *   2. 看全文（skill_md）
 *   3. 应用 / 取消应用 / 删除
 *
 * 生成和改正文在「写稿 › 工作台」。只读写法（内置、证据蒸馏）不能在工作台改，
 * 但必须能在这里应用——所以这页不能因为「工作台已经能生成」就下线。
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Button from "../components/Button";
import Drawer from "../components/Drawer";
import EmptyState from "../components/EmptyState";
import Markdown from "../components/Markdown";
import { SkeletonList } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { ApiError, get, unwrapList } from "../lib/api";
import { invalidate, useQuery } from "../lib/query";
import {
  applyStyle,
  deleteStyle,
  displayChars,
  groupStyleProfiles,
  loadStyleDetail,
  loadStyleProfiles,
  sourceLabel,
  unapplyStyle,
  type StyleProfileDetail,
  type StyleProfileSummary,
} from "../lib/styleLibrary";
import "./StyleLibraryPanel.css";

interface Account {
  id: number;
  nickname?: string;
  status?: string;
}

export default function StyleLibraryPanel() {
  const toast = useToast();
  const navigate = useNavigate();

  const accounts = useQuery(
    () => get("/api/accounts").then((r) => unwrapList<Account>(r)),
    [],
    { key: "styles|accounts", staleTime: 60_000 },
  );
  const activeAccount = (accounts.data?.items ?? []).find((a) => a.status === "active");

  /*
   * 按账号取写法。
   *
   * `apply` 是按账号绑定的。列表不按账号过滤时，多账号场景会把另一个账号的
   * applied 行显示成「当前生效」，而点「取消应用」后端会报「这个风格当前应用在
   * 账号 A」——页面又没有账号切换器，是条死路。
   *
   * 传了 accountId 之后列表只剩「未绑定 + 本账号」，`applied` 必然属于本账号。
   */
  const profiles = useQuery(
    () => loadStyleProfiles(100, activeAccount?.id ?? null),
    [activeAccount?.id],
    {
      key: `styles|list|${activeAccount?.id ?? "none"}`,
    },
  );

  const [detail, setDetail] = useState<StyleProfileDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  /** 展开了哪几个组（key）。默认全收起，只看见每组一行。 */
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());

  const items = profiles.data?.items ?? [];
  const applied = items.find((p) => p.status === "applied");
  const groups = groupStyleProfiles(items);

  function toggleGroup(key: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function openDetail(id: number) {
    setDetailLoading(true);
    try {
      setDetail(await loadStyleDetail(id));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "读不到这份写法");
    } finally {
      setDetailLoading(false);
    }
  }

  async function toggleApply(id: number, isApplied: boolean) {
    if (!activeAccount) {
      toast.error("还没有可用的小红书账号，先去「账号」页绑定");
      return;
    }
    setBusyId(id);
    try {
      if (isApplied) {
        await unapplyStyle(id, activeAccount.id);
        toast.success("已取消应用；这份写法保留在库里");
      } else {
        await applyStyle(id, activeAccount.id);
        toast.success("已应用，写稿和后端生成都会按这份写法来");
      }
      /*
       * 应用动作本身就是 PATCH，返回即生效——生成时后端按账号读 applied 的那份。
       * 这里原来有一次「重新推给写稿宿主」的调用，宿主已退场，一并去掉。
       */
      invalidate("styles");
      setDetail(null);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "操作失败");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(id: number) {
    setBusyId(id);
    try {
      await deleteStyle(id);
      toast.success("已删除");
      invalidate("styles");
      setDetail(null);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  }

  if (accounts.initialLoading || profiles.initialLoading) {
    return <SkeletonList rows={4} />;
  }

  if (!activeAccount) {
    return (
      <EmptyState
        glyph="flow"
        title="还没有小红书账号"
        description="写法是应用到账号上的。先去「设置 → 账号」扫码绑定，再回来挑写法。"
      />
    );
  }

  return (
    <div className="sl">
      <div className={`sl__banner${applied ? " is-on" : " is-off"}`}>
        <span>
          <b className="sl__banner-k">
            {applied ? `当前生效：${applied.name}` : "当前没有生效的写法"}
          </b>
          <br />
          {applied
            ? `@${activeAccount.nickname ?? activeAccount.id} · ${sourceLabel(applied.source)} · ${displayChars(applied)} 字。写稿和生成都按它来。`
            : "没有生效写法时，写稿只会用账号定位 + 通用方法。挑一份应用就好。"}
          <br />
          这一页只负责「应用 / 取消应用 / 删除」。生成新写法、改正文去「写稿 › 工作台」；
          跨作者的爆款结构去「写法与能力 › 蒸馏」。
        </span>
      </div>

      {items.length === 0 ? (
        <EmptyState
          glyph="stack"
          title="还没有任何写法"
          description="去「写稿 › 工作台」勾几篇样本生成一份，或在「写法与能力 › 蒸馏」跑一次证据蒸馏。生成后回到这里应用。"
          action={
            <Button variant="primary" onClick={() => navigate("/write/studio")}>
              去工作台
            </Button>
          }
        />
      ) : (
        <ul className="sl__list">
          {groups.map((group) => {
            const p = group.leader;
            const isApplied = p.status === "applied";
            const open = openGroups.has(group.key);
            const extra = group.versions.length - 1;
            return (
              <li className="sl__row sl__row--group" key={group.key}>
                <div className="sl__row-main">
                  <span className="sl__row-title">
                    {p.name}
                    {p.builtin_key ? <span className="sl__tag sl__tag--builtin">内置</span> : null}
                    {isApplied ? <span className="sl__tag sl__tag--applied">生效中</span> : null}
                    {extra > 0 ? (
                      <button
                        className="sl__tag sl__tag--more"
                        onClick={() => toggleGroup(group.key)}
                        title="同一批素材蒸出来的其他版本"
                      >
                        {open ? `收起 ${extra} 个版本` : `同批 ${extra} 个版本`}
                      </button>
                    ) : null}
                  </span>
                  <span className="sl__row-meta">
                    {sourceLabel(p.source)} · {displayChars(p)} 字
                    {p.works_count > 0 ? ` · ${p.works_count} 篇` : ""}
                    {group.versions.length > 1
                      ? ` · 同批素材 ${group.versions.length} 份，这里显示一份`
                      : ""}
                    {p.summary?.positioning ? ` · ${p.summary.positioning.slice(0, 34)}` : ""}
                  </span>
                </div>

                <div className="sl__row-acts">
                  <button className="sl__link" onClick={() => void openDetail(p.id)}>
                    看全文
                  </button>
                  <button
                    className="sl__link"
                    disabled={busyId === p.id}
                    onClick={() => void toggleApply(p.id, isApplied)}
                  >
                    {busyId === p.id ? "处理中…" : isApplied ? "取消应用" : "应用到账号"}
                  </button>
                  <button
                    className="sl__link sl__link--danger"
                    disabled={busyId === p.id || isApplied}
                    title={isApplied ? "生效中的写法先取消应用再删" : undefined}
                    onClick={() => void remove(p.id)}
                  >
                    删除
                  </button>
                </div>

                {open ? (
                  <ul className="sl__versions">
                    {group.versions.slice(1).map((v) => (
                      <VersionRow
                        key={v.id}
                        profile={v}
                        busy={busyId === v.id}
                        onOpen={() => void openDetail(v.id)}
                        onToggleApply={() =>
                          void toggleApply(v.id, v.status === "applied")
                        }
                        onRemove={() => void remove(v.id)}
                      />
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <p className="sl__note">
        写法来自四条路：工作台、样本提炼、抖音提炼、证据蒸馏，加上内置（ego）。
        不管从哪来，应用后只有一个生效——应用新的会让旧的退回「未生效」，旧的仍然保留在库里
        （不会删，也不会消失）。
        能改正文的只有工作台的那几类；证据蒸馏的正文是给人看的报告，内置是产品内容，
        这两类不能改，但都能在这里应用或取消。
      </p>

      <Drawer
        open={Boolean(detail) || detailLoading}
        title={detail ? detail.name : "写法"}
        width={760}
        onClose={() => setDetail(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDetail(null)}>
              关掉
            </Button>
            {detail ? (
              <Button
                variant={detail.status === "applied" ? "ghost" : "primary"}
                loading={busyId === detail.id}
                onClick={() => void toggleApply(detail.id, detail.status === "applied")}
              >
                {detail.status === "applied" ? "取消应用" : "应用到账号"}
              </Button>
            ) : null}
          </>
        }
      >
        {detailLoading && !detail ? <p className="sl__note">正在读全文…</p> : null}
        {detail ? (
          <div className="sl__detail">
            <div className="sl__detail-meta">
              <span>{sourceLabel(detail.source)}</span>
              <span>· {detail.engine}</span>
              <span>· {displayChars(detail)} 字</span>
              {detail.works_count > 0 ? <span>· {detail.works_count} 篇</span> : null}
              <span>· {detail.status === "applied" ? "生效中" : "未生效"}</span>
            </div>
            {detail.engine === "evidence" ? (
              /*
               * 证据型的正文是「关于写作的报告」（覆盖率、自述与实测不一致、
               * 体裁共性），模型实际拿到的是规则块。不说清这一点，人会以为
               * 「自述与实测不一致」这些段落也被喂给模型了，或者以为改正文有用。
               */
              <p className="sl__note">
                这份是证据蒸馏：下面全文是给人看的报告，模型收到的是从
                `injectable_rules` 里挑出来的规则。正文不能在工作台里改——要调整请回蒸馏页改语料重跑。
              </p>
            ) : null}
            <div className="sl__detail-md">
              <Markdown text={detail.skill_md || "（这份写法没有正文）"} />
            </div>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}

/** 折叠区里的一行旧版本。样式和主行一致，只是缩进、字号小一档。 */
function VersionRow({
  profile,
  busy,
  onOpen,
  onToggleApply,
  onRemove,
}: {
  profile: StyleProfileSummary;
  busy: boolean;
  onOpen: () => void;
  onToggleApply: () => void;
  onRemove: () => void;
}) {
  const isApplied = profile.status === "applied";
  const historical = profile.name.includes("历史");
  return (
    <li className="sl__version">
      <div className="sl__row-main">
        <span className="sl__row-title">
          <span className="sl__version-name">{profile.name}</span>
          {historical ? <span className="sl__tag">历史</span> : null}
          {isApplied ? <span className="sl__tag sl__tag--applied">生效中</span> : null}
        </span>
        <span className="sl__row-meta">
          {sourceLabel(profile.source)} · {displayChars(profile)} 字
          {profile.works_count > 0 ? ` · ${profile.works_count} 篇` : ""}
        </span>
      </div>
      <div className="sl__row-acts">
        <button className="sl__link" onClick={onOpen}>
          看全文
        </button>
        <button className="sl__link" disabled={busy} onClick={onToggleApply}>
          {busy ? "处理中…" : isApplied ? "取消应用" : "应用到账号"}
        </button>
        <button
          className="sl__link sl__link--danger"
          disabled={busy || isApplied}
          title={isApplied ? "生效中的写法先取消应用再删" : undefined}
          onClick={onRemove}
        >
          删除
        </button>
      </div>
    </li>
  );
}
