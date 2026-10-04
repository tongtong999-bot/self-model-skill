# 本地记录工具：给执行 Skill 的 AI

仅在有文件/执行工具和 Python 3.9+ 时使用。以下命令由 AI 执行，不要求普通用户手写 JSON。无可用环境时用 Markdown 档案降级，不自动安装环境或宣称程序已运行。

工具不联网、不读取环境密钥、不开服务、不调用 AI。只读指定输入及内置题库；个人文件须位于 Skill 和 Git 仓库以外。记录工具写入 JSON，不能直接读写 v0.1 的 Markdown 档案。

## 路径与授权

- `RUNNER` 指本 Skill 下 `scripts/self_model.py` 的绝对路径。参考文件相对于本 Skill，不依赖仓库工作目录。
- `PROFILE` 是用户指定的私人 JSON 档案路径；只在用户要求保存/持续记录后建立。如果位置未知，只需确认一次。父目录须已存在或在已授权位置创建。
- `INPUT` 是私人目录中的临时 JSON 文件。用文件工具写入，不将用户原文插进 shell 命令。操作后删除自己创建的临时输入文件；它也可能包含隐私。
- 后续写入使用已有授权。不要把资料保存到源码、安装目录、公开 Issue 或 GitHub，也不要擅自改账户或发送消息。
- 命令中的占位路径需要替换并正确引用。不要实际创建名为 `PROFILE` 的示例文件。

```text
python3 RUNNER init --profile PROFILE
python3 RUNNER status --profile PROFILE
python3 RUNNER catalog --section baseline --start 1 --count 4
python3 RUNNER catalog --section scenarios
python3 RUNNER catalog --section topics
python3 RUNNER catalog --section dimensions
python3 RUNNER show --profile PROFILE --run RUN_ID
python3 RUNNER show --profile PROFILE --story STORY_ID
python3 RUNNER show --profile PROFILE --evidence EVIDENCE_ID
python3 RUNNER model --profile PROFILE
python3 RUNNER show --profile PROFILE --dossier
python3 RUNNER show --profile PROFILE --report
python3 RUNNER export --profile PROFILE --out NEW_PRIVATE_READING_MD
```

初始化默认个人档案；**仅虚构演示用 `init --demo`**，不要把示例混入个人档案。`status` 返回 revision、资料指纹 inputDigest 和各段进度。`show --dossier` 仅用于需要整合材料的分析，不默认读取所有个人记录。

### 写入方式

```text
python3 RUNNER apply --profile PROFILE --expected-revision 7 --input INPUT
```

读取最新 revision 后，将本次真实用户输入整理为操作对象。每次新操作用新的 `requestId`；网络/工具重试时使用**完全相同**的对象和编号，避免重复提交。程序拒绝过期 revision、同编号不同内容和不完整的数据，失败时保留原档。出现冲突先重新读取，不能猜新 revision 强行覆盖。

本地写锁失败时不自动删除锁或抢占；先确认没有运行中的写入。程序采用临时文件替换，类 Unix 系统写出的档案权限为 0600；其他系统仍受其文件权限与同步设置影响。

## 操作契约

每个对象都包含 `requestId`（字符串）与 `op`。以下字段列在对象顶层，除非明确写为内嵌对象。

| op | 其他字段 |
| --- | --- |
| `context.set` | `context: {goal?, preserve?, constraints?, roles?}`；只写用户已表达的内容 |
| `baseline.answer` | `answers: [{questionId: "b1", value: 1..5}, ...]`；更新原题，不追加重复答案 |
| `baseline.finish` | 无；必须已答齐 24 题 |
| `scenario.start` | `scenarioId: "flood" / "command" / "startup"`；返回 runId |
| `scenario.request` | `runId, nodeId`，以及内置 `informationId` 或自由 `question` |
| `scenario.decide` | `runId, nodeId, choiceId, reasoning, priority`；自定方案需 `choiceId: "custom", custom`；可选 `prediction` |
| `interview.start` | `topicId`；返回 storyId 与首问 |
| `interview.answer` | `storyId, round: 1..4, answer`；前三轮另需 `nextQuestion`；可选用户自选 `priority` |
| `interview.finish` | `storyId`；用于导入网站已答四轮但未点完成的访谈 |
| `record.add` | `fact, action, context, reflection`；存近期经历，不计为完整访谈 |
| `correction.add` | `finding, text`；记录用户修正并作废旧报告 |
| `practice.create` | `question, desired, preserve, context, constraint, capacity: "light" / "room", evidenceIds: []`；返回 cycleId |
| `practice.plan` | `cycleId, plan: {optionId, title, trigger, action, why, observe, stop, prediction}`；暂停后需用户明确恢复，才可设 `resume: true` |
| `practice.review` | `cycleId, attemptId, review: {attempted: "yes" / "partly" / "no", actual, learning, next: "continue" / "adjust" / "pause", nextAction}` |
| `source.delete` | `sourceId`；基线用 `baseline`，其他用记录编号，删除影响见下方 |
| `report.save` | `report: {...}`；按下一节结构校验后保存 |

`priority` 必须来自 `catalog --section dimensions` 中的 id。它代表用户主动表达的主要因素。不要根据 AI 的印象替用户填入。计划中的 `prediction` 未提供时写“用户尚未提供，暂不确定”，不能写成用户认可了 AI 的预测。只有用户选定了动作，才调用 `practice.plan`；候选方案留在对话或报告里。

### 一次写入示例（虚构）

```json
{
  "requestId": "example-answer-01",
  "op": "baseline.answer",
  "answers": [{"questionId": "b1", "value": 4}]
}
```

不要重复使用示例编号处理真实的新操作。`apply` 成功后用返回进度继续；向用户只说本轮已记录和下一步问题，无需展示技术字段。

## 报告结构与检查

从当前 dossier 获取 `inputDigest` 和原始证据 id，不自行重编号。报告 JSON 结构：

```text
inputDigest: 当前资料指纹
status: draft | complete
summary: 当前处境与总结
observations: [{id, claim, evidenceIds: [真实编号], conditions, alternative, unknown}]
people: [{
  id, name, field, evidenceIds: [真实编号], differences: [至少两项],
  verification: browsed | provided | unverified,
  sources: [{id, title, url?, text: 实际查阅的短节选, accessedAt}],
  facts: [{id, statement, sourceId, quote: 上述节选中连续存在的支持片段}],
  path: {
    direction, conditions, benefit, cost, risk,
    experiment: {trigger, action, why, observe, stop}
  }
}]
comparison: 三条方向的条件和取舍
unknowns: [尚不清楚的内容]
review: {kind: self-review | independent-review, notes: 实际复核方式与仍有的局限}
```

`field` 使用 `science, arts, business, engineering, healthcare, education, sports, public-service, humanities` 中一个；三人须不同领域，且人工复查实际领域重叠及同人别名。`complete` 要求三位人物、个人观察、每人的具体事实与来源。无网络时用 `draft`；候选人物设 `unverified`，其 sources/facts 为空，仍可保留待探索方向。用户提供材料用 `provided`，不要谎称联网。

```text
python3 RUNNER report-check --profile PROFILE --input REPORT_JSON
```

程序检查资料指纹、证据引用、人数、字段、关键差异、来源归属和连续引文。**通过只表示结构与引用内部一致，不表示来源真实、论证成立或人格解释准确。** 不编写一段“原文”来让自己的引用通过。浏览节选只保留必要短片段，报告优先转述并附链接。

按 [portraits.md](portraits.md) 做语义复核，再把报告包进 `report.save` 操作写入。`review.kind` 如实写独立复核或自查，不能把同一轮重读说成另一模型核验。保存失败时修正明确错误，最多两次；仍不通过就交付明确标注的草稿和未解决问题，不声称已保存成功。

## 导入、导出与删除

网站导出的 **version: 1 原始 Profile JSON** 可以导入到新文件：

```text
python3 RUNNER import --profile NEW_PRIVATE_PROFILE --input WEBSITE_EXPORT
```

导入会验证原始记录，保留示例标记，移除旧 AI 报告与支付解锁标记，不覆盖原文件。格式不受支持时说明具体限制，不猜测字段或强行重置；这不是浏览器存储、数据库、账户的全量迁移。v0.1 Markdown 档案需要 AI 读取并按真实内容逐步整理，不能自动反推从未记录的问卷答案或模拟选择。

JSON 档案本身就是可携带备份。用户要求阅读版时，用 `export` 在指定私人位置生成 Markdown，包括进度、15 维线索、当前报告、用户修正、人物出处、未完成行动及原始依据。它按已保存内容生成，不需要 AI 再改写一次，也不会把过期报告导成当前结果。目标已有文件时会拒绝覆盖，请另选文件名。不得承诺能无损导回网站。

删除按**来源**执行。`source.delete` 会移除该来源、证据、引用它的行动及复盘，清空可能包含旧解释的修正与重试缓存，并作废整份报告。执行前说明当前档案中的影响范围；仅在用户已要求删除该来源及其派生内容时使用。只删除一段文字或改一道题时，不能悄悄删除更大的来源组，可先澄清范围或提供局部编辑方案。

删除不会清理平台聊天、旧导出副本或系统备份。程序不会自动创建这些副本；如用户需要备份，应保存到其指定私人位置。只报告实际处理过的文件。
