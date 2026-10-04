# Self Model · 观己

**从一件真实经历开始，理解自己的选择，再找到一个可以尝试的小行动。**

一个中文优先的 AI Skill，将自我访谈、情境演练、人物路径比较和行动复盘串成对话。使用你已有的 AI；无需部署网站、购买域名或配置本项目的 API Key。

A conversational Agent Skill for self-understanding, decision exploration, and reflective action. Chinese-first; responds in the user's language.

[查看 Skill](skills/self-model/SKILL.md) · [看一段虚构体验](examples/conversation.md) · [下载安装包](https://github.com/tongtong999-bot/self-model-skill/releases/latest)

## 最快开始：在 Codex 中使用

**第一步：把下面这段话发给 Codex。**

```text
请使用 $skill-installer 安装这个 Skill：
https://github.com/tongtong999-bot/self-model-skill/tree/main/skills/self-model
如果已经有同名 Skill，请先告诉我，不要覆盖。
```

**第二步：安装完成后，在下一轮对话输入：**

```text
使用 $self-model，帮助我认识自己。
从我最近的一件困扰开始，每次只问一个主要问题，不要急着给我贴标签。
```

**第三步：按自己的节奏回答。** 可以随时说“跳过”“这个判断不对”“换个情境”“先总结”或“暂停”。不必先填完整套问卷。

**第四步：有需要时继续深入。**

```text
根据我们聊过的内容，整理当前的自我模型。
找三位不同行业的历史或当代人物作为参照，查阅来源，
比较他们的选择、与我的差异，以及我可以试的三条方向。
最后给我一个这周能开始的小尝试。
```

安装器会使用当前 Codex 的 Skill 目录。若当前客户端没有提供安装器，可下载仓库，并将整个 `skills/self-model` 文件夹放入该客户端配置的个人 Skill 目录，不能只复制 `SKILL.md`。

## 其他使用方式

### Claude Code

将以下文字发给有文件和网络权限的 Claude Code：

```text
请从 https://github.com/tongtong999-bot/self-model-skill
下载 skills/self-model 文件夹，安装到 ~/.claude/skills/self-model。
保留所有参考文件。如果该目录已存在，不要覆盖，先告诉我。
```

随后输入：

```text
/self-model 从我最近的一件困扰开始，帮我理解自己，并找到一个可尝试的小行动。
```

目录和调用方式见 [Claude Code 官方 Skill 文档](https://code.claude.com/docs/en/skills)。

### Claude 的自定义 Skills

从 [Releases](https://github.com/tongtong999-bot/self-model-skill/releases/latest) 下载 **`self-model.zip`**，在 Claude 的自定义 Skills 界面上传并启用，然后说“请用 self-model 帮我认识自己”。上传的是这个专用包，不是 GitHub 自动生成的整个仓库源码 ZIP。

需要账户具有对应功能并启用代码执行，具体入口以 [Claude 官方说明](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills) 为准。本项目本身不包含可执行脚本。

### 其他 AI 聊天工具

如果工具能读取文件，可以解压安装包，将 `SKILL.md` 和这次需要的参考文件作为附件提供，并要求按其流程对话。这属于手动使用，**不代表工具已安装 Skill 或拥有跨会话记忆**。无法读取附件时，可复制相关文本。

## 它可以帮你做什么

| 你可以说 | 会如何开展 |
| --- | --- |
| “我想认识自己，不知道从哪里开始” | 从一个近期事件开始，逐步了解做法、条件和在意的东西 |
| “给我一个情境，看看我怎么选择” | 进行明确标注为虚构的演练，回看权衡过程 |
| “我为什么总在同类事情上纠结？” | 对照经历与反例，提出可以修正的解释 |
| “找三位人物，看看有哪些发展方向” | 动态选择跨领域人物，查阅事实，说明相似处、关键差异和路径代价 |
| “别只分析，我这周可以做什么？” | 比较少量选择，形成一个适合当前资源的小尝试 |
| “这是我试过以后的结果” | 比较预期与实际，更新理解，允许调整和暂停 |

它不会预装一份“你就是某某名人”的名单。人物来自当前 AI 对具体资料的分析；有联网能力时查阅出处，没有时明确标为待研究候选。人物故事用于拓宽选择，不能预测人生。

## AI 在哪里起作用

Skill 是一套可复用的工作方法，**运行它的 AI 负责访谈、理解、提出假设、检索人物资料、比较路径和整理行动**。因此结果质量依赖使用的模型及其可用工具。

本项目没有独立服务器、共享密钥、账号系统或付费解锁。公开内容采用 MIT 许可；使用 AI 产生的订阅或 API 费用由使用者自己的平台收取。已经在 Codex 或 Claude 中对话时，无需为这个 Skill 再接一次 GLM API。

## 如何保留自己的记录

默认在当前对话中工作。希望下次继续时，告诉 AI：

```text
请把这次的关键经历、当前理解、我的修正和行动状态保存成个人档案。
只保存必要信息，放到我指定的私人文件夹，不要放进 Skill 目录或 GitHub 仓库。
```

然后提供自己的保存位置。下次指定该档案，请 AI 先读再继续。没有文件工具时，让 AI 给出摘要，自己保存并在下次提供。模板见 [个人档案模板](skills/self-model/assets/profile.md)。

本项目不自建数据收集服务，也不要求上传档案给作者。但与 AI 的对话、文件读取和搜索仍受所用平台的数据规则影响，不能把“本地文件”理解成“模型完全离线”。请用化名或省去无关身份信息；不要把真实经历和隐私放到公开 Issue 中。

## 方法与边界

工作方法借鉴人格与情境研究、叙事身份、社会学角色理论、自我调节和实施意图；具体依据及本项目自己的设计判断见 [方法说明](skills/self-model/references/methods.md)。

这是自我探索与行动支持工具，**不是心理诊断、标准化人格测验或效果经过验证的治疗方案**。问答、模拟、经历自述和现实记录会区分来源；不生成虚构的准确率或人格相似度。用户可以纠正解释，AI 应同步调整建议。

## 项目结构

```text
skills/self-model/
├── SKILL.md                       对话入口与共同规则
├── agents/openai.yaml             Codex 展示信息
├── references/
│   ├── exploration.md             经历、问答与情境演练
│   ├── portraits.md               完整解析与人物路径
│   ├── action-and-review.md       行动与复盘
│   └── methods.md                 方法依据与限制
└── assets/profile.md              可选个人档案模板
examples/conversation.md           完全虚构的体验示例
```

遵循 `SKILL.md` 包结构，无运行依赖。参考资料按任务需要读取。首次发布已检查格式与引用，并用虚构资料试用了初次访谈、离线分析与档案保存、联网人物路径三个场景。兼容格式不代表在每个 AI 客户端上都做过实际运行测试；Claude 客户端尚未实机验证。

## 修改与分享

欢迎使用、修改和分享，保留 [MIT 许可](LICENSE)。反馈时描述交互问题并使用虚构或脱敏例子。这个仓库只维护通用方法、模板与示例，不收集使用者的个人档案。
