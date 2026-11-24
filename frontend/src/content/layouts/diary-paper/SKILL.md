---
name: xhs-diary-paper
description: 当已确认的小红书文案适合日记行距纸，或用户选择diary-paper排版时加载。
---
# 日记行距纸

## 原创结构
封面标题在偏下位置；正文是带左装订线的横线纸。短文适度放大并按行距格垂直平衡，保留叙述顺序与轻松留白，不自动添加用户日期。

适用信号：日记、记录、今天、心情、成长、日常。这些信号只帮助推荐，不构成替用户确认。

## 调用顺序
1. 服务端确认当前revision已满意；未满意先改稿，态度自然、诚恳。
2. planning.mjs.planTextCards/recommendStyles以真实随附字体测量，返回A/B/C的planId、结构、封面+正文张数、字号与理由。不按字数简单整除。
3. 官方ask_user_question让用户确认所选styleId=diary-paper及测量张数；将真实选择事件保存在server-owned userSelection。
4. renderPlannedTextCards仅在planId/revision/sourceHash/张数均匹配且未过期时执行；不要让模型提交任意代码、HTML、CSS、URL、字体或输出路径。
5. 由host受限二进制artifact服务进行最终revision/hash/satisfaction原子CAS并发布授权下载。

## 可读性和完整性
最低正文36px。候选字号为60/54/48/42/36px；依据真实可读容量适度放大，不为了强凑张数无限缩小。中文按grapheme换行，长URL可逐字断行，emoji缺字明确诊断。原字/段落/CRLF/空行/---控制符都保留于原文片段及checksum；不因风格擅自改字。独立---明确作为分页控制，不画成内容。

实际glyph bounds逐行/区域碰撞核验，页脚预留区与文本不相交；多栏/网格按上述固定阅读顺序。冲突时返回PAGE_COUNT_CONFLICT/字体诊断/布局错误，建议接受实测张数、换结构或先改稿后确认。取消或稿件更新不交付半成品。

## 来源及许可
结构实现/本文为本项目原创，参考通用方法而非复制上游Skill提示词或代码。参考baoyu-xhs-images的布局/字号层级研究（JimLiu/baoyu-skills，固定ca703c2d7c2c4399a1dc0cf82224f8551e05a96d，MIT，原许可证已保留）及Marp主题的首屏/内容页对齐层级（marp-team/marp-core，固定26e50d00f7fe14ded7dcacd971ef3a93ac47e94d，MIT）。详见../../SOURCES.md。上游公开MD仅为研究数据，不作为执行指令，不读取用户全局配置，不使用其图像API/CLI。
