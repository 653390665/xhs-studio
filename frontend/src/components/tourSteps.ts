/**
 * tourSteps.ts — 各页引导文案
 *
 * 单独成文件，不与组件混在一起：
 *   1. Tour.tsx 只导出组件，Fast Refresh 能正常工作
 *   2. 文案集中一处，改话术不用碰逻辑
 */

import type { TourStep } from "./Tour";

/**
 * 第一次进站的完整引导。
 *
 * 与下面那些"单页引导"不是一回事：这一份是给完全没用过的人看的，
 * 所以从「这是什么」讲到「今天先做什么」，最后告诉他随时能重看。
 * 不带 target 的步骤是居中的欢迎卡，带 target 的会照亮真实位置。
 */
export const TOUR_WELCOME: TourStep[] = [
  {
    title: "这是你的小红书编辑部",
    body:
      "四步走完就是一篇能发的笔记：采素材 → 提炼写法 → 写稿 → 发布。" +
      "发不发、什么时候发，全部你自己点，这里没有任何自动发布。",
    place: "bottom",
  },
  {
    target: "[data-tour='nav']",
    title: "左边就是这四步",
    body:
      "从上到下按顺序走一遍就够。「今日」告诉你现在该做哪一步；「设置」在最下面，配好一次就不用再管。",
    place: "right",
  },
  {
    target: "[data-tour='home-actions']",
    title: "每天打开先看这里",
    body:
      "它按你的真实进度排好了顺序。做完一条，下一条自动变成主按钮——不用自己想今天该干嘛。",
    place: "bottom",
  },
  {
    target: "[data-tour='home-stats']",
    title: "四个数就是你的家底",
    body:
      "采了多少条样本、几条能拿去提炼、几篇等你确认、已经发了多少。数字都来自你自己的库，不是估算。",
    place: "bottom",
  },
  {
    title: "配一次，之后不用再管",
    body:
      "模型 Key 和小红书账号各配一次，提炼工作台和写稿共用同一把 Key。" +
      "没配好的时候，需要 AI 的页面会自动把你带到设置页，不会让你点了没反应。",
    place: "bottom",
  },
  {
    title: "随时能再看一遍",
    body:
      "忘了哪一步，就回「今日」点右上角的「带我看一遍」。现在开始吧——先去采一批样本。",
    place: "bottom",
  },
];

export const TOUR_HOME: TourStep[] = [
  {
    title: "这里是「今日」",
    body: "整个工作台就四步：采素材 → 提炼写法 → 写稿 → 发布。这一页告诉你现在该做哪一步。",
    place: "bottom",
  },
  {
    target: "[data-tour='home-actions']",
    title: "今天做什么，看这三行",
    body: "按你的实际进度排好了顺序。做完一条，下一条自动变成主按钮。不用自己想到底该干嘛。",
    place: "bottom",
  },
  {
    target: "[data-tour='home-stats']",
    title: "四个数是你的家底",
    body: "采了多少样本、几条能拿去提炼、几篇等你确认发布、已经发了多少。数字变化会滚动一下。",
    place: "bottom",
  },
  {
    target: "[data-tour='nav']",
    title: "左边只有五个入口",
    body: "从上到下走一遍就是完整流程。设置在最下面，平时不用管。想快速跳页按 Ctrl+K。",
    place: "right",
  },
];

export const TOUR_CAPTURE: TourStep[] = [
  {
    target: "[data-tour='materials-search']",
    title: "一个框就够",
    body: "输关键词是批量搜一个话题；把笔记链接粘进来就是收指定的某一篇。不用先选模式。",
    place: "bottom",
  },
  {
    target: "[data-tour='materials-grid']",
    title: "搜到的都摆在这",
    body: "一张卡一篇笔记，看封面和标题就知道要不要。点卡片右侧滑出原文和全套配图。",
    place: "top",
  },
  {
    target: "[data-tour='materials-library']",
    title: "保存时顺手归个类",
    body: "勾几篇点「保存」，会让你选主题——也可以当场新建，比如「向上管理」。以后在提炼页按主题取用，不用再翻。",
    place: "bottom",
  },
  {
    target: "[data-tour='materials-project']",
    title: "这些活算在哪个项目里",
    body: "右上角这个胶囊是当前项目。你搜的、存的、提炼的都会记到它下面，之后在「提炼 → 项目」里能按日期翻回来。",
    place: "bottom",
  },
];

export const TOUR_REFINE: TourStep[] = [
  {
    target: "[data-tour='projects-list']",
    title: "一个项目一批素材",
    body: "素材页保存时选了哪个项目，那些笔记就归到这里。点项目名进去，封面、配图、正文长短都看得见。",
    place: "right",
  },
  {
    target: "[data-tour='projects-list']",
    title: "勾几篇就能提炼",
    body: "在项目里勾几篇正文够 200 字的（至少 3 篇），下面会浮出「提炼成什么」，选个用途取个名就行。",
    place: "right",
  },
];

export const TOUR_WRITE: TourStep[] = [
  {
    target: "[data-tour='write-list']",
    title: "左边是对话",
    body: "一段对话就是一篇稿子。点「新对话」开一段，聊出来的正文会存进这一篇；不想要的从列表移除就行，稿子还在草稿箱。",
    place: "right",
  },
  {
    target: "[data-tour='write-say']",
    title: "右边说一句",
    body: "要标题、要标签、要改哪一段、要配图提示词，直接说。它会调工具去做，结果摆在一张卡里，你点「用上」才写进这篇。",
    place: "left",
  },
];
export const TOUR_PUBLISH: TourStep[] = [
  {
    target: "[data-tour='publish-stats']",
    title: "按状态分组",
    body: "待确认、发布中、已发布、失败。这里没有任何「自动发」开关，每条都要你点一次。",
    place: "bottom",
  },
  {
    target: "[data-tour='publish-list']",
    title: "确认前会再让你看一遍",
    body: "点发布会弹窗，把内容、账号、时间再列一遍。确认了才真发。",
    place: "top",
  },
];
