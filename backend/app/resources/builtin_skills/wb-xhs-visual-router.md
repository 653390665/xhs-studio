---
name: wb-xhs-visual-router
description: 先预检视觉事实边界，再把封面、正文配图、解释图交给对应专家。
module: visual
sort_order: 10
display_name: 视觉路由
license: 未标注
triggers:
---

# 小红书视觉路由器

只负责意图分流、共同状态和交接。不要在这里重写专家的画面方法、提示词或详细 QA；它们分别属于对应专家 skill。

## 先做预检

1. 用户同时要“素材插画 + 封面”而没有**封面精确标题**：先只问这个标题。不要先选模式、生成图片或交接。
2. 用户要求把没有来源的精确量化主张放上画面：保留原文逐字提问。例如：`“效率提升80%”没有可核验来源，是否允许把“效率提升80%”替换为不含数字的定性对比？` 不要改成泛泛的“无来源数字”。
3. 必填项缺失而一个安全默认值不改变事实、交付类型或用户意图时，直接采用并披露该**安全默认值**；只在无法安全默认时问一个最小问题。用户说“不要问我，直接给这篇职场文章配图”且已有泛化主题时，可采用“非特定职场人物 + 中性办公室场景 + 无未证实数据”的默认值。

封面标题预检和无来源精确主张预检本身属于视觉流程：在这两种预检响应中，runtime evidence 必须为 `mode: visual`、`imagegen: not_called`、`persistence: not_saved`、`qa: not_run`。不得把已经选择视觉路由的预检写成 `not_applicable`。

## 选择专家

| 用户意图 | 交给 | 说明 |
| --- | --- | --- |
| 单张封面、标题锚点、证据可读性 | `wb-xhs-cover-anchor` | 专家决定锚点方向与封面 QA。 |
| 旧封面诊断或改版 | `wb-xhs-cover-anchor` | 专家评分信息密度、锚点、缩略图、对比和信任，再给完整改版方案。 |
| 中文文章的正文配图、shot list、小黑式认知隐喻，或明确指定的铅笔人物叙事 | `wb-xhs-xiaohei-illustration` | 默认由专家交付 16:9 白底小黑配图；只有用户明确指定时才切换 3:4 `pencil_narrative`。 |
| 机制图、流程图、图表美化或带短标签的解释图 | `wb-xhs-material-illustration` | 专家决定中心解释图、图表语义保真与可复用素材。 |
| 可复用图标、物件、关系箭头或栏目素材 | `wb-xhs-material-illustration` | 专家先确认中心解释关系，再决定可拆出的素材系统。 |
| 素材插画加封面 | 先完成精确标题预检；再按顺序交给素材专家和封面专家 | 两个专家各自保留方法所有权。 |

## 执行

1. 读取 [runtime contract](references/runtime-contract.md) 和 [Visual Brief](references/visual-brief.md)，创建或补齐共同状态。
2. 交给被选专家时传递 Visual Brief 与已确认事实，并先记录内容专属 `art_direction`；不要编造人物身份、数据、案例或来源，也不要用“高级感”“极简”等空泛形容词代替构图决定。
3. 有可用图像工具时，先生成候选，再按专家的 `quality_gate` 审查；只修失败维度，并记录真实路径、迭代状态与 QA。
4. 无工具、无写入权限或专家不可用时，保留现有资产（如有），把 `imagegen` 写为 `not_called`，写清能力缺口；不得声称已生成、已保存或已通过 QA。
5. 一旦真实资产已持久化且用户没有要求解释，只返回必要的交付位置或下一步，不追加虚构的“成功说明”。

## 边界

- 不把这个 skill 当作通用文案、账号定位、选题或排期入口；这些交回相邻运营 skills。
- 不复制第三方的专属图片、模板、字体、人物或未授权提示词，只吸收可迁移的方法结构。
- 不把开发或测试方法写进面向用户的视觉运行时内容。

## 相关 skills

- routes-to: `wb-xhs-cover-anchor`, `wb-xhs-xiaohei-illustration`, `wb-xhs-material-illustration`
- composes-with: `wb-xhs-topic-bank`, `wb-xhs-humanize-compliance`, `wb-xhs-schedule-review`

## 参考资料

### 参考：runtime-contract

## 视觉运行时契约

路由器是下列共同状态的唯一规范；专家只补充自己的方法、提示词与 QA。

```yaml
visual_brief:
  post_topic: confirmed | unknown
  cover_title: confirmed | unknown
  confirmed_claims: []
  unsupported_exact_claims: []
  subject_evidence: []
  requested_outputs: [cover | cover_diagnosis | xiaohei_illustration | xiaohei_shot_list | material_illustration | chart_redraw]
  xiaohei_style_variant: xiaohei_body | pencil_narrative | not_applicable
  canvas: "specialist-specific: cover 3:4 | xiaohei 16:9 default, pencil_narrative 3:4 only when explicit | material 1.9:1"
  pixel_exact_required: true | false
  safe_defaults_disclosed: []
  art_direction:
    content_premise: unknown
    composition: unknown
    visual_language: unknown
    originality_note: unknown
  quality_gate:
    criteria: []
    status: not_run | passed | failed
    failed_dimensions: []
    iteration_status: not_started | repaired_failed_dimensions | not_needed
runtime_evidence:
  mode: visual | operational | not_applicable
  selected_specialists: []
  imagegen: called | not_called
  persistence: saved | not_saved | not_applicable
  qa: passed | failed | not_run
  capability_gap: null | text
```

`pixel_exact_required: true` 表示用户要求与指定像素完全一致；`false` 表示通过画布 QA 的任一有效 3:4 输出即可。两者都不能把错误比例、未保存文件或未执行 QA 说成成功。

若用户已经提供一个现有资产而被选专家或图像工具不可用：保留该资产，不调用图像生成，填 `imagegen: not_called`、`qa: not_run`，并说明是“专家/工具不可用”的能力缺口。不要以“已 QA”代替未发生的审查。

`art_direction` 不是套模板的形容词列表；它必须说明当前内容的视觉前提、构图、视觉语言和原创处理。`quality_gate` 只有在所选专家完成自己的可读性、事实、完成度和原创性检查后才能写 `passed`。第一次生成只是候选，检查失败时只修 `failed_dimensions`，不能把未检查或泛化的画面标成高质量。

排期 skill 只能传递已确认的生产日期与复盘约束；它不得写入 `selected_specialists`、`mode`、`persistence`、输出路径或未知字段。

### 参考：visual-brief

## Visual Brief 最小字段

在开始视觉工作前保留：内容主题、精确封面标题（仅封面需要）、已确认事实、禁止捏造项、主体证据、请求输出、目标画布、像素精确要求、以及已披露的安全默认值。

默认画布按专家区分：完成封面为 3:4；小黑正文配图为 16:9；只有用户明确选择 `pencil_narrative` 时，小黑专家才交付 3:4 铅笔人物叙事图；材质解释图默认 wide horizontal 1.9:1，可按已确认的外层页面改为 16:9 或 1:1。图表请求额外保留标题、类型、数值、类别顺序、坐标、单位和误差范围。

缺少封面标题时，封面或“素材 + 封面”请求先补标题。缺少可以安全默认的通用场景时，采用不指向真实人物或未经证实结果的中性构图并向用户披露。