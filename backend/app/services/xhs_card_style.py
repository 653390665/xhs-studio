"""小红书图文卡片的「风格 × 布局」预设，以及提示词装配。

为什么要单独一个模块
--------------------
生图不是「给一句话让模型自由发挥」——那样十次出十种东西，没法发。实测：
正文首段 + "无文字、无水印" 会产出插画、图表或空白纸；而把**逐行文字写死**
之后，3/5/7/9 行、190 字长文、5 种风格全部零错字。

所以提示词必须由结构拼装：
    规格 → 原则 → 风格 → 布局 → 内容（逐行写死）→ 克制规则

风格与布局分开建模，是因为它们正交：
  · 风格决定颜色/质感/装饰（notion 的墨线、screen-print 的平涂套印）
  · 布局决定信息密度与结构（dense 的网格、list 的清单、comparison 的左右对照）
同一句话可以「便签风 + 清单」也可以「便签风 + 对照」，互不干扰。

参考（思路，非代码）
--------------------
- baoyu-xhs-images：11 风格 × 8 布局 + 预设组合 + 参考图链（无 LICENSE，仅参考结构）
- RedInk（CC BY-NC-SA）：页面分 封面/内容/总结 三类各自的排版要求
- ian-xhs-carousel（MIT）：字号档位、「一页一处强调色」、「十秒读完」
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# 小红书图文原生比例。后端下发 size 字符串，网关按 WxH 解析。
DEFAULT_SIZE = "1024x1365"
ALLOWED_SIZES = ("1024x1365", "1024x1024", "1365x1024")


@dataclass(frozen=True)
class StylePreset:
    key: str
    label: str
    # 方向：给前端分组用
    group: str
    summary: str
    # 会逐字拼进提示词
    palette: str
    texture: str
    typography: str
    decorations: str
    # 该风格要避免的东西（反 AI 味）
    avoid: str
    # 风格强到不适合画字时（比如 screen-print 的字型很硬），文案要短
    max_lines: int = 9


@dataclass(frozen=True)
class LayoutPreset:
    key: str
    label: str
    summary: str
    structure: str
    density: str
    whitespace: str
    max_lines: int


STYLES: dict[str, StylePreset] = {
    "notion": StylePreset(
        key="notion",
        label="手绘知识卡",
        group="知识",
        summary="极简手绘线条，黑白灰 + 淡彩点缀，信息密度高但不挤",
        palette="背景纯白或米白（#FFFFFF / #FAFAFA），正文近黑（#1A1A1A），"
                "次要文字深灰（#4A4A4A），点缀只用一种淡彩（#A8D4F0 或 #F9E79F，"
                "二选一，不要两种同时出现）",
        texture="干净纸面，可有极轻微的纸纹；不要渐变、不要光影、不要 3D",
        typography="手写感中文标题，单字笔画均匀，正文用清晰的无衬线手写体",
        decorations="少量手绘短线和波浪下划线；关键词用圆圈或下划线标记",
        avoid="不要蓝紫渐变、不要发光、不要立体图标、不要摄影实拍",
        max_lines=9,
    ),
    "minimal": StylePreset(
        key="minimal",
        label="极简留白",
        group="观点",
        summary="大量留白，一到两行大字，靠字号和间距撑气场",
        palette="米白或浅灰纸面，文字纯黑，强调色只用一处极细的朱红",
        texture="纸面干净，留白处不要任何装饰",
        typography="字形端正的中文黑体或宋体，字距略松",
        decorations="最多一条细横线或一个小编号",
        avoid="不要插画、不要图标、不要边框、不要阴影",
        max_lines=4,
    ),
    "warm": StylePreset(
        key="warm",
        label="暖调生活",
        group="生活",
        summary="暖米色、柔和阴影、生活感，适合日常与情绪内容",
        palette="暖米色背景（#F5EDE0 附近），文字深褐，点缀暖橘",
        texture="柔和自然光，轻微纸张或布纹质感",
        typography="圆润的中文字体，标题可略粗",
        decorations="小而克制的实物元素（便签角、胶带边），不要堆砌",
        avoid="不要冷色霓虹、不要科技感线条、不要过度饱和",
        max_lines=7,
    ),
    "bold": StylePreset(
        key="bold",
        label="强烈对比",
        group="冲击",
        summary="大色块高对比，适合避坑、警告、正反观点",
        palette="背景与文字强对比（深底浅字或浅底深字），强调色只用一种高饱和色",
        texture="平涂色块，边缘干脆",
        typography="粗黑体，标题字号明显大于正文",
        decorations="粗色块、粗下划线、粗箭头；不做细描边",
        avoid="不要柔和渐变、不要粉彩、不要繁复细节",
        max_lines=7,
    ),
    "retro": StylePreset(
        key="retro",
        label="复古印刷",
        group="风格化",
        summary="泛黄旧纸、网点、套印错位，适合盘点与怀旧",
        palette="泛黄纸底（#E8DCC0 附近），墨黑文字，朱红套印",
        texture="可见纸纤维与网点，轻微污渍与折痕",
        typography="老式印刷宋体，字重偏重",
        decorations="朱红套印轻微错位、边角磨损、细线框",
        avoid="不要干净数码感、不要纯白底、不要现代图标",
        max_lines=9,
    ),
    "pop": StylePreset(
        key="pop",
        label="活泼波普",
        group="冲击",
        summary="亮色块 + 粗描边，适合趣味冷知识与轻松分享",
        palette="白底 + 两到三种高饱和亮色块，文字深色",
        texture="平涂，无渐变；可有网点或斜纹做底",
        typography="粗圆体，标题可带一点手写倾斜",
        decorations="粗描边的形状、圆点、箭头，元素彼此错落",
        avoid="不要低饱和、不要极简、不要写实照片",
        max_lines=7,
    ),
    "study": StylePreset(
        key="study",
        label="手写笔记",
        group="知识",
        summary="蓝笔正文 + 红笔标注 + 黄色高亮，像真实学习笔记",
        palette="白纸底，正文深蓝黑，标注朱红，高亮淡黄",
        texture="真实纸张，可有横线或方格底纹",
        typography="自然手写中文，字迹工整但有人味",
        decorations="关键词用黄色马克笔高亮，重点旁加红笔下划线和简短标注",
        avoid="不要印刷体、不要矢量图标、不要居中排版",
        max_lines=9,
    ),
    "editorial": StylePreset(
        key="editorial",
        label="杂志编辑",
        group="观点",
        summary="大标题 + 栏目标签 + 细线分隔，克制的高级感",
        palette="米白纸面，黑字为主，一处朱红点缀",
        texture="细腻纸纹，可有极轻的印刷网点",
        typography="宋体大标题（可竖排），正文用清晰黑体，字号层级分明",
        decorations="栏目标签、细横线、编号；留白大方",
        avoid="不要插画、不要彩色块、不要圆角卡片堆叠",
        max_lines=7,
    ),
}


LAYOUTS: dict[str, LayoutPreset] = {
    "list": LayoutPreset(
        key="list",
        label="清单",
        summary="每行一条，行首统一符号，最稳也最好读",
        structure="单栏纵向排列，每行一条；行首统一使用同一种符号（圆点或编号），"
                  "不要混用；行距一致，行与行之间不要加分隔线",
        density="中",
        whitespace="四周留出明显边距，底部至少留四分之一空白",
        max_lines=9,
    ),
    "balanced": LayoutPreset(
        key="balanced",
        label="均衡",
        summary="标题 + 段落正文，最通用的图文内页",
        structure="上方标题，下方正文；正文按语义分段，段与段之间留一个空行的高度；"
                  "左对齐，不要居中，不要首行缩进",
        density="中",
        whitespace="标题与正文之间留出明显间距",
        max_lines=8,
    ),
    "dense": LayoutPreset(
        key="dense",
        label="高密度",
        summary="信息量大时用，分区块、每块带小标题",
        structure="把内容分成二到四个区块，每块有一个小标题和若干条要点；"
                  "区块之间用细线或留白隔开，不要用色块",
        density="高",
        whitespace="区块内部紧凑，区块之间留白；页边距不能省",
        max_lines=12,
    ),
    "comparison": LayoutPreset(
        key="comparison",
        label="左右对照",
        summary="正反、前后、误区与正解",
        structure="画面纵向分成左右两栏，中间一条细竖线；左栏一个小标题加若干条，"
                  "右栏一个小标题加若干条；两栏文字块高度尽量对齐",
        density="中",
        whitespace="两栏内侧各自留白，不要贴到中线上",
        max_lines=8,
    ),
    "flow": LayoutPreset(
        key="flow",
        label="步骤流程",
        summary="按顺序排一二三四，带箭头或序号",
        structure="自上而下排列步骤，每步一个大序号和一行说明；"
                  "步骤之间用细箭头或短竖线连接；序号与说明基线对齐",
        density="中",
        whitespace="步骤之间等距，最后一个步骤下方留白",
        max_lines=7,
    ),
    "sparse": LayoutPreset(
        key="sparse",
        label="大字留白",
        summary="一句话撑满一页，封面和金句专用",
        structure="只放一到三行大字，居中或偏上；其余全部留白；不配任何图形",
        density="低",
        whitespace="至少一半画面是空的",
        max_lines=3,
    ),
}


# 内容场景 → (风格, 布局)。用户不选时按内容自动推荐。
PRESETS: dict[str, dict[str, str]] = {
    "knowledge-card": {"style": "notion", "layout": "dense", "label": "干货知识卡"},
    "checklist": {"style": "notion", "layout": "list", "label": "清单必看"},
    "study-guide": {"style": "study", "layout": "dense", "label": "学习笔记"},
    "tutorial": {"style": "notion", "layout": "flow", "label": "步骤教程"},
    "warning": {"style": "bold", "layout": "list", "label": "避坑提醒"},
    "versus": {"style": "bold", "layout": "comparison", "label": "正反对照"},
    "clean-quote": {"style": "minimal", "layout": "sparse", "label": "金句封面"},
    "cozy-story": {"style": "warm", "layout": "balanced", "label": "生活分享"},
    "retro-ranking": {"style": "retro", "layout": "list", "label": "复古盘点"},
    "pop-facts": {"style": "pop", "layout": "list", "label": "趣味冷知识"},
    "editorial": {"style": "editorial", "layout": "balanced", "label": "观点长文"},
}


def _style_block(style: StylePreset) -> str:
    return "\n".join(
        [
            f"## 风格：{style.label}",
            f"{style.summary}",
            "",
            f"- 配色：{style.palette}",
            f"- 质感：{style.texture}",
            f"- 字体：{style.typography}",
            f"- 装饰：{style.decorations}",
            f"- 禁止：{style.avoid}",
            "- **只允许在文字上做强调（加粗/圈选/下划线/高亮）；"
            "不要给条目添加它没有的分类标题或编号**",
        ]
    )


def _layout_block(layout: LayoutPreset) -> str:
    return "\n".join(
        [
            f"## 布局：{layout.label}",
            f"- 结构：{layout.structure}",
            f"- 信息密度：{layout.density}",
            f"- 留白：{layout.whitespace}",
        ]
    )


PAGE_TYPE_RULES = {
    "cover": "\n".join(
        [
            "## 本页是封面",
            "- 标题字号是全部页面里最大的，占画面上部主要位置",
            "- 副标题（如果有）紧跟标题下方，字号约为标题的三分之一到四分之一",
            "- 封面只放标题和副标题两部分，不要提前把内容页的条目搬上来",
            "- 不要在封面上堆正文条目",
        ]
    ),
    "content": "\n".join(
        [
            "## 本页是内容页",
            "- 保持与封面的同一套配色与质感，只换内容",
            "- 标题（如有）字号明显小于封面，但仍要大于正文",
            "- 条目之间层次清楚，重点行可以加粗或加一处强调色",
            "- 不要再加页面序号或页码，除非上面明确要求",
        ]
    ),
    "summary": "\n".join(
        [
            "## 本页是收尾页",
            "- 只画上面给出的文字，**不要自己写总结句、鼓励语、口号**",
            "- 可以有一个勾选或完成感的图形符号（不配文字）",
            "- 结尾留白比内容页更多",
        ]
    ),
}


def resolve_preset(preset: str | None, style: str | None, layout: str | None) -> tuple[str, str]:
    """把 preset / style / layout 三者归一成 (style_key, layout_key)。

    显式的 style / layout 永远盖过 preset —— 和上游那套约定一致。
    """
    base = PRESETS.get(preset or "", {})
    style_key = style or base.get("style") or "notion"
    layout_key = layout or base.get("layout") or "list"
    if style_key not in STYLES:
        style_key = "notion"
    if layout_key not in LAYOUTS:
        layout_key = "list"
    return style_key, layout_key


def _numbered_lines(lines: Iterable[str]) -> str:
    out = []
    for i, line in enumerate(lines, start=1):
        out.append(f"  {i}. 「{line}」")
    return "\n".join(out)


def build_page_prompt(
    *,
    title: str,
    lines: list[str],
    page_type: str = "content",
    style_key: str = "notion",
    layout_key: str = "list",
    index: int = 1,
    total: int = 1,
    size: str = DEFAULT_SIZE,
    extra_instruction: str = "",
    illustration: str = "none",
    illustration_hint: str = "",
) -> str:
    """拼一页的提示词。

    关键约束（都是实测出来的，不是拍脑袋）：
      1. 文字逐行写死，且明说「必须逐字准确，不得修改、增删、简写」
         —— 否则模型会自己总结、省略，或把条目标题改写。
      2. 明确「所有文字必须完整出现在画面内」—— 否则会出现只画前两行。
      3. 禁止项单独成段 —— 混在正文里会被忽略。
      4. 文字不能旋转、倒置 —— 模型偶尔会为了"设计感"把竖排字画反。
    """
    style = STYLES.get(style_key) or STYLES["notion"]
    layout = LAYOUTS.get(layout_key) or LAYOUTS["list"]
    page_rule = PAGE_TYPE_RULES.get(page_type, PAGE_TYPE_RULES["content"])

    width, _, height = size.lower().partition("x")
    ratio = "3:4" if (width, height) == ("1024", "1365") else "1:1"

    parts = [
        f"（本次生成第 {index}/{total} 张，这个页码只是给你定位用，**不要画进画面**）",
        "",
        "## 规格",
        f"- 画布：竖版 {ratio}，{size}",
        "- 满幅出血，不要手机边框、不要白色外留边、不要圆角裁切预览",
        "",
        "## 文字（最高优先级）",
        "- 以下文字必须逐字准确出现在画面里：不得修改、不得增删、不得简写、不得换同义词",
        "- 所有文字必须完整显示在画面内，不能被裁掉、不能被遮挡、不能只画一部分",
        "- 文字一律水平正向，不得旋转、不得倒置、不得镜像",
        "- **严禁给条目添加任何序号或分类前缀**（如「误区一」「要点 1」「第一」「①」）；"
        "条目原文是什么就画什么，一个字都不要加",
        "- **严禁自行补写任何句子**（总结句、鼓励语、解释句、口号）；"
        "下面的文字就是全部内容，多一个字都不要",
        "- 同一段文字只出现一次，不要为了版面重复排版",
        "",
        f"  标题：「{title}」",
    ]
    if lines:
        parts.append("  正文条目（逐行，顺序不变）：")
        parts.append(_numbered_lines(lines))
    parts += [
        "",
        "## 逐行核对（最容易错的地方，务必照做）",
        "- 上面每一条都用「」括起来了；画的时候**逐条抄写括号里的字**，",
        "  一条对应画面里的一行，顺序和条数都不能变",
        "- 相邻两条如果开头一样（例如都以「不是」开头），**不要把后半句串到上一条**；",
        "  每一条的结尾以它自己的最后一个字为准",
        "- **一行太长放不下时，缩小字号或折成两行，绝不能删掉任何字**。",
        "  宁可字小一点，也不能少字——少一个字整张图就废了",
        "- 画完在心里默读一遍：行数 = 上面条目数，每行首尾字都与原文一致",
        "",
        "## 文字排版",
        "- 标题字号明显大于正文；正文行距一致，行与行之间不要挤在一起",
        "- 中文断行要自然，不要把一个词拆到两行",
        "- 不要出现任何额外的文字、水印、账号 id、平台 logo、页脚",
        "- 不要用引号把条目括起来（「」『』以及英文双引号都不要），那只是给你的标记",
        "",
        _style_block(style),
        "",
        _layout_block(layout),
        "",
        page_rule,
        "",
        "## 克制规则",
        "- 一页只留一处强调色，其余文字用主色",
        "- 一页的内容要能十秒读完；放不下就减少条目，不要缩小字号硬塞",
        "- 装饰元素 serve 内容，不要为了填满画面加无意义的图形",
    ]
    if total > 1:
        parts += [
            "",
            "## 系列一致性",
            "- 与系列中其它页面使用完全相同的配色、质感与字体层级，只换内容",
        ]
    if illustration in ("icon", "scene"):
        parts += ["", _illustration_block(illustration, style, illustration_hint)]
    if extra_instruction.strip():
        parts += ["", "## 额外要求", extra_instruction.strip()]
    return "\n".join(parts)


_ILLUSTRATION_RULES = {
    "icon": (
        "## 插图：一个小图标\n"
        "- 只在标题旁或留白处放**一个**与内容相关的极简图标，尺寸不超过画面宽度的八分之一\n"
        "- 图标用与风格一致的线条或色块，不要写实、不要彩色立体\n"
        "- 图标**不能压住任何文字**，也不能替代文字"
    ),
    "scene": (
        "## 插图：一幅场景插画\n"
        "- 画面**下方约 40%** 放一幅与内容主题相关的插画，上半部分留给文字\n"
        "- 插画风格必须与本页配色、笔触一致；扁平或手绘，不要照片写实、不要 3D、不要渐变霓虹\n"
        "- **插画绝对不能压住、遮挡、替换任何文字**；文字区与插画区要清晰分开\n"
        "- 插画里不要出现任何文字、字幕、标牌上的字"
    ),
}


def _illustration_block(mode: str, style: StylePreset, hint: str) -> str:
    block = _ILLUSTRATION_RULES.get(mode)
    if not block:
        return ""
    if hint.strip():
        block += f"\n- 画面内容参考：{hint.strip()}"
    block += f"\n- 与整体风格的协调：{style.texture}"
    return block


def presets_payload() -> dict:
    """给前端的预设清单（不含提示词正文）。"""
    return {
        "sizes": list(ALLOWED_SIZES),
        "default_size": DEFAULT_SIZE,
        "illustrations": [
            {"key": "none", "label": "纯文字", "summary": "最稳，不插图"},
            {"key": "icon", "label": "小图标", "summary": "标题旁一个极简图标"},
            {"key": "scene", "label": "场景插画", "summary": "下方 40% 一幅插画，最好看也最占版面"},
        ],
        "styles": [
            {
                "key": s.key,
                "label": s.label,
                "group": s.group,
                "summary": s.summary,
                "max_lines": s.max_lines,
            }
            for s in STYLES.values()
        ],
        "layouts": [
            {
                "key": l.key,
                "label": l.label,
                "summary": l.summary,
                "max_lines": l.max_lines,
            }
            for l in LAYOUTS.values()
        ],
        "presets": [
            {"key": k, "label": v["label"], "style": v["style"], "layout": v["layout"]}
            for k, v in PRESETS.items()
        ],
    }
