#!/usr/bin/env python3
"""Local-only state, fixed exploration, and structural report checks. Python 3.9+."""
import argparse
import copy
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path
import sys
import tempfile
import unicodedata
from urllib.parse import quote, urlparse

from model import (CATALOG, DIMENSIONS, QUESTIONS, SCENARIOS, TOPICS, LABELS,
                   aggregate, baseline_evidence, create_run, current_node,
                   make_decision, new_profile, now, readiness, request_information,
                   require, text, uid)

LIMIT = 10 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(profile):
    data = {k: profile.get(k) for k in ("id", "demo", "answers", "baselineCompleted", "runs", "stories", "evidence", "reportFocus", "reportFeedback")}
    data["practices"] = [{k: v for k, v in c.items() if k != "aiAdvice"} for c in profile.get("practices", [])]
    data["context"] = profile.get("_skill", {}).get("context", {})
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def read_json(path):
    path = Path(path).expanduser()
    require(not path.is_symlink(), "请使用普通文件，不使用符号链接")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as f:
        raw = f.read(LIMIT + 1)
    require(len(raw) <= LIMIT, "文件超过 10 MB；请先缩减资料，不自动截断")
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "JSON 中有重复字段")
            result[k] = v
        return result
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("JSON 不接受非有限数字")))


def writable_path(path):
    path = Path(path).expanduser().absolute()
    require(not path.is_symlink(), "拒绝覆盖符号链接")
    resolved = path.resolve()
    skill = Path(__file__).resolve().parents[1]
    require(skill not in resolved.parents, "个人档案不能写入 Skill 安装目录")
    for parent in resolved.parents:
        require(not (parent / ".git").exists(), "请把个人档案放在 Git 仓库外的私人文件夹")
    require(path.parent.is_dir(), "保存目录不存在，请先准备用户指定的私人目录")
    return path


def atomic_write(path, value, as_text=False):
    # Caller holds a same-directory exclusive lock. No history or hidden backup copies.
    fd, tmp = tempfile.mkstemp(prefix=".self-model-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if hasattr(os, "fchmod"):
                os.fchmod(f.fileno(), 0o600)
            f.write(value if as_text else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Lock:
    def __init__(self, path):
        self.path = path.with_name(path.name+".lock")

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise ValueError("档案正在写入或遗留锁文件；确认没有运行中的操作后再处理锁，不自动抢占")
        os.close(fd)

    def __exit__(self, *args):
        self.path.unlink()


def number(value, low, high):
    require(type(value) in (int, float) and low <= value <= high, "数值超出范围")


def unique(rows, key="id"):
    require(isinstance(rows, list), "应为列表")
    ids = [text(r[key], "编号", maximum=200) for r in rows]
    require(len(set(ids)) == len(ids), "存在重复编号")
    return set(ids)


def validate_profile(p):
    require(isinstance(p, dict) and type(p.get("version")) is int and p["version"] == 1, "不支持的档案版本")
    for k in ("id", "name", "updatedAt"):
        text(p[k], k, maximum=500)
    for k in ("demo", "baselineCompleted", "onboarded", "remoteAI"):
        require(type(p[k]) is bool, f"{k} 应为布尔值")
    unique(p["answers"], "questionId")
    for a in p["answers"]:
        require(a["questionId"] in QUESTIONS and type(a["value"]) is int and 1 <= a["value"] <= 5, "基线题号或回答无效")
    require(not p["baselineCompleted"] or len(p["answers"]) == 24, "基线未满 24 题，不能标为完成")
    sources = unique(p["runs"]) | unique(p["stories"]) | unique(p.get("practices", []))
    require(len(sources) == len(p["runs"])+len(p["stories"])+len(p.get("practices", [])), "来源编号重复")
    run_ids = {r["id"] for r in p["runs"]}
    history_ids = sources-run_ids
    for r in p["runs"]:
        require(r["scenarioId"] in SCENARIOS and type(r["completed"]) is bool, "情境记录无效")
        scenario = SCENARIOS[r["scenarioId"]]
        replay = create_run(scenario)
        unique(r["events"])
        for e in r["events"]:
            require(e["nodeId"] == replay["currentNodeId"], "情境顺序不连续")
            require(e["stateBefore"] == replay["state"], "情境初始资源与记录不一致")
            validate_requests(e["requests"], current_node(replay, scenario))
            replay["pendingRequests"] = e["requests"]
            replay, _ = make_decision(replay, scenario, dict(e, custom=e["choiceText"]))
            generated = replay["events"][-1]
            require(all(e[k] == generated[k] for k in ("stateAfter", "choiceText", "consequence")), "情境后果被改写，与固定规则不符")
        require(r["state"] == replay["state"] and r["currentNodeId"] == replay["currentNodeId"] and r["completed"] == replay["completed"], "情境进度不一致")
        if r["completed"]:
            require(r["pendingRequests"] == [], "完成情境不能保留未提交的信息请求")
        else:
            validate_requests(r["pendingRequests"], current_node(r, scenario))
    for s in p["stories"]:
        require(s["topicId"] in TOPICS or s["topicId"] == "recent", "未知访谈主题")
        unique(s["messages"])
        for m in s["messages"]:
            require(m["role"] in ("user", "assistant"), "访谈角色无效")
            text(m["content"], maximum=4000)
        if s["topicId"] != "recent":
            require(len(s["messages"]) <= 8, "固定访谈最多四轮")
            require(all(m["role"] == ("assistant" if i % 2 == 0 else "user") for i, m in enumerate(s["messages"])), "访谈问答顺序不一致")
            count = len([m for m in s["messages"] if m["role"] == "user"])
            require(type(s["completed"]) is bool and (not s["completed"] or count == 4), "访谈完成标记不一致")
        if s.get("priority"):
            require(s["priority"] in DIMENSIONS, "访谈考虑因素无效")
    eids = unique(p["evidence"])
    for e in p["evidence"]:
        require(e["sourceType"] in ("self_report", "historical", "simulated", "reasoning"), "证据类型无效")
        require(e["sourceId"] in sources | {"baseline"}, "证据缺少原始来源")
        require(e["context"] in CATALOG["contextNames"] and type(e["pressure"]) is bool, "证据情境无效")
        if e["sourceType"] == "self_report":
            require(e["sourceId"] == "baseline", "基线来源不一致")
            require(e["groupId"] == "baseline" and e["id"] in {"baseline-"+a["questionId"] for a in p["answers"]}, "基线证据不能脱离原题")
        elif e["sourceType"] in ("simulated", "reasoning"):
            require(e["sourceId"] in run_ids, "模拟证据没有对应情境")
            run = next(r for r in p["runs"] if r["id"] == e["sourceId"])
            require(e["groupId"] in {v["id"] for v in run["events"]}, "模拟选择及理由必须归入原事件")
        else:
            require(e["sourceId"] in history_ids, "经历证据没有对应记录")
        for k in ("id", "groupId", "title", "observation"):
            text(e[k], maximum=16000)
        if "quote" in e:
            text(e["quote"], maximum=20000)
        require(isinstance(e["hypotheses"], list), "假设应为列表")
        for h in e["hypotheses"]:
            require(h["dimension"] in DIMENSIONS, "假设维度无效")
            for k, low in (("direction", -1), ("weight", 0), ("confidence", 0)):
                number(h[k], low, 1)
            text(h["reason"])
            require(isinstance(h["alternatives"], list) and len(h["alternatives"]) >= 1, "假设应保留其他解释")
    for c in p.get("practices", []):
        for k in ("question", "desired", "preserve", "context", "constraint"):
            text(c[k], maximum=600)
        require(c["capacity"] in ("light", "room"), "精力字段无效")
        require(set(c["evidenceIds"]) <= eids, "行动引用了不存在的证据")
        unique(c["attempts"])
        for i, attempt in enumerate(c["attempts"]):
            validate_plan(attempt)
            require(i == len(c["attempts"])-1 or "review" in attempt, "旧尝试尚未复盘")
            if "review" in attempt:
                validate_review(attempt["review"])
    for f in p.get("reportFeedback", []):
        text(f["finding"], maximum=1800)
        text(f["text"], maximum=600)
    if "_skill" in p:
        meta = p["_skill"]
        require(meta["format"] == 2 and type(meta["revision"]) is int and meta["revision"] >= 0, "Skill 档案版本无效")
        require(isinstance(meta["requests"], dict) and isinstance(meta["context"], dict), "Skill 元数据无效")
        require(set(meta["context"]) <= {"goal", "preserve", "constraints", "roles"}, "未知关注字段")
        for value in meta["context"].values():
            text(value, maximum=2000)
    return p


def validate_requests(requests, node):
    unique(requests)
    require(len(requests) <= 12, "信息请求超过本轮上限")
    for r in requests:
        require(type(r["custom"]) is bool, "信息请求类型无效")
        text(r["question"])
        if not r["custom"]:
            item = next((i for i in node["availableInformation"] if f'{node["id"]}-{i["id"]}' == r["id"]), None)
            require(item is not None and all(r[k] == item[k] for k in ("question", "answer", "category")), "信息答案与情境不一致")
        else:
            require(r["answer"] == "现有情境资料无法回答这个问题。该信息缺口已记录，你可以在理由中说明它如何影响选择。", "自由问题不得编造固定情境答案")


def validate_plan(data):
    for k in ("optionId", "title", "trigger", "action", "why", "observe", "stop", "prediction"):
        text(data[k], k, maximum=600)


def validate_review(data):
    require(data["attempted"] in ("yes", "partly", "no") and data["next"] in ("continue", "adjust", "pause"), "复盘状态无效")
    for k in ("actual", "learning", "nextAction"):
        text(data[k], k, maximum=600)


def validate_report(report, profile):
    require(isinstance(report, dict), "报告应为对象")
    require(report["inputDigest"] == digest(profile), "报告对应旧资料，必须重新分析")
    require(report["status"] in ("draft", "complete"), "报告状态无效")
    text(report["summary"], maximum=5000)
    eids = {e["id"] for e in profile["evidence"]}
    def refs(row):
        require(isinstance(row["evidenceIds"], list) and bool(row["evidenceIds"]) and set(row["evidenceIds"]) <= eids, "报告引用了缺失或空证据")
    unique(report["observations"])
    require(len(report["observations"]) <= 8, "请聚焦最多八项观察")
    for o in report["observations"]:
        refs(o)
        for k in ("claim", "conditions", "alternative", "unknown"):
            text(o[k], k, maximum=3000)
    people = report["people"]
    unique(people)
    require(len(people) <= 3 and (report["status"] != "complete" or len(people) == 3), "完整报告须有三个人物；资料不足使用 draft")
    names, fields = set(), set()
    for p in people:
        refs(p)
        name = unicodedata.normalize("NFKC", text(p["name"])).casefold().replace(" ", "")
        require(name not in names, "人物重复")
        names.add(name)
        field = text(p["field"])
        require(field in ("science", "arts", "business", "engineering", "healthcare", "education", "sports", "public-service", "humanities"), "人物领域须使用规定编号")
        require(field not in fields, "人物主要领域重复；也需人工检查同业与别名")
        fields.add(field)
        require(isinstance(p["differences"], list) and len(p["differences"]) >= 2, "每位人物至少两项关键差异")
        for difference in p["differences"]:
            text(difference)
        require(p["verification"] in ("browsed", "provided", "unverified"), "人物查阅状态无效")
        unique(p["sources"])
        sources = {s["id"]: s for s in p["sources"]}
        for s in p["sources"]:
            text(s["title"], maximum=500)
            text(s["text"], "实际查阅的节选", maximum=12000)
            text(s["accessedAt"], maximum=100)
            if p["verification"] == "browsed":
                parsed = urlparse(s.get("url", ""))
                require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password, "人物出处应为公开 HTTPS 链接")
                host = parsed.hostname.lower()
                require("." in host and not host.endswith((".local", ".internal", ".localhost")), "人物出处不能使用本地地址")
                try:
                    addr = ipaddress.ip_address(host)
                except ValueError:
                    pass
                else:
                    require(addr.is_global, "人物出处不能使用私网地址")
        unique(p["facts"])
        for fact in p["facts"]:
            text(fact["statement"], maximum=1600)
            require(fact["sourceId"] in sources, "人物事实没有对应来源")
            quote = text(fact["quote"], "来源支持片段", maximum=1000)
            require(quote in sources[fact["sourceId"]]["text"], "来源中不存在报告所引片段")
        if p["verification"] == "unverified":
            require(not p["facts"] and not p["sources"], "未查阅的人物只能列为候选，不能附带伪核验事实")
        if report["status"] == "complete":
            require(p["verification"] != "unverified" and bool(p["facts"]), "完整人物报告需要每人的来源与具体事实")
        path = p["path"]
        for k in ("direction", "conditions", "benefit", "cost", "risk"):
            text(path[k], k, maximum=3000)
        for k in ("trigger", "action", "why", "observe", "stop"):
            text(path["experiment"][k], k, maximum=1000)
    text(report["comparison"], maximum=5000)
    require(isinstance(report["unknowns"], list) and bool(report["unknowns"]), "报告必须保留未知")
    for unknown in report["unknowns"]:
        text(unknown)
    review = report["review"]
    require(review["kind"] in ("self-review", "independent-review"), "必须说明是自查还是独立复核")
    text(review["notes"], maximum=4000)
    if report["status"] == "complete":
        require(bool(report["observations"]), "完整报告需要个人观察")
    return {"structure": "passed", "truthVerifiedByProgram": False, "review": review["kind"], "status": report["status"]}


def find(rows, identity):
    row = next((r for r in rows if r["id"] == identity), None)
    require(row is not None, "找不到指定记录")
    return row


def history_evidence(profile, story):
    evidence_id = "story-"+story["id"]
    profile["evidence"] = [e for e in profile["evidence"] if e["sourceId"] != story["id"]]
    answers = [m["content"] for m in story["messages"] if m["role"] == "user"]
    hypotheses = []
    if story.get("priority"):
        hypotheses = [dict(dimension=story["priority"], direction=.5, weight=.35, confidence=.35,
                           reason="用户在回顾中主动选择的主要因素，仍是自述线索。",
                           alternatives=["角色、资源或回忆方式也可能解释这一选择。"])]
    profile["evidence"].append(dict(id=evidence_id, sourceId=story["id"], groupId=story["id"],
        sourceType="historical", title=story["title"], observation="未经外部核实的经历自述；同一经历的多轮回答为一组材料。",
        quote="\n\n".join(answers), context="life", pressure=False, hypotheses=hypotheses, createdAt=now()))


def operate(p, data):
    op = data["op"]
    if op == "context.set":
        require(isinstance(data["context"], dict) and set(data["context"]) <= {"goal", "preserve", "constraints", "roles"}, "关注字段无效")
        for k, v in data["context"].items():
            p["_skill"]["context"][k] = text(v, k, maximum=2000)
        return {"context": p["_skill"]["context"]}
    if op == "baseline.answer":
        unique(data["answers"], "questionId")
        answers = {a["questionId"]: a["value"] for a in p["answers"]}
        for a in data["answers"]:
            require(a["questionId"] in QUESTIONS and type(a["value"]) is int and 1 <= a["value"] <= 5, "回答应为已知题号与 1–5 整数")
            answers[a["questionId"]] = a["value"]
        p["answers"] = [dict(questionId=q, value=answers[q]) for q in QUESTIONS if q in answers]
        p["evidence"] = [e for e in p["evidence"] if e["sourceId"] != "baseline"]+baseline_evidence(p)
        return {"answered": len(answers)}
    if op == "baseline.finish":
        require(len(p["answers"]) == 24, "还有题目未答；不把跳过或未知填成居中答案")
        p["baselineCompleted"] = True
        return {"baselineComplete": True}
    if op == "scenario.start":
        require(data["scenarioId"] in SCENARIOS, "未知场景")
        require(not any(r["scenarioId"] == data["scenarioId"] and not r["completed"] for r in p["runs"]), "已有未完成场景，请先继续或明确删除该场景")
        run = create_run(SCENARIOS[data["scenarioId"]])
        p["runs"].append(run)
        return {"runId": run["id"]}
    if op in ("scenario.request", "scenario.decide"):
        run = find(p["runs"], data["runId"])
        require(data["nodeId"] == run["currentNodeId"], "题目已变化，请重新读取当前节点")
        scenario = SCENARIOS[run["scenarioId"]]
        if op == "scenario.request":
            updated = request_information(run, scenario, data.get("informationId"), data.get("question"))
            result = {"requests": updated["pendingRequests"]}
        else:
            updated, evidence = make_decision(run, scenario, data)
            p["evidence"].extend(evidence)
            result = {"event": updated["events"][-1], "evidenceIds": [e["id"] for e in evidence]}
        p["runs"][p["runs"].index(run)] = updated
        return result
    if op == "interview.start":
        require(data["topicId"] in TOPICS, "未知访谈主题")
        topic = TOPICS[data["topicId"]]
        require(not any(s["topicId"] == topic["id"] and not s["completed"] for s in p["stories"]), "请先继续已有访谈")
        story = dict(id=uid(), topicId=topic["id"], title=topic["title"], completed=False, provider="skill", createdAt=now(),
                     messages=[dict(id=uid(), role="assistant", content=topic["prompt"], createdAt=now())])
        p["stories"].append(story)
        return {"storyId": story["id"], "question": topic["prompt"]}
    if op == "interview.answer":
        story = find(p["stories"], data["storyId"])
        require(not story["completed"] and story["messages"][-1]["role"] == "assistant", "访谈不在等待回答状态")
        count = sum(m["role"] == "user" for m in story["messages"])
        require(data["round"] == count+1, "访谈轮次已变化")
        answer = text(data["answer"], "本轮回答", 8)
        if count < 3:
            followup = text(data["nextQuestion"], "下一轮追问")
        story["messages"].append(dict(id=uid(), role="user", content=answer, createdAt=now()))
        if count < 3:
            story["messages"].append(dict(id=uid(), role="assistant", content=followup, createdAt=now()))
        else:
            story["completed"] = True
        if data.get("priority"):
            require(data["priority"] in DIMENSIONS, "未知因素")
            story["priority"] = data["priority"]
        history_evidence(p, story)
        return {"storyId": story["id"], "answeredRounds": count+1, "completed": story["completed"]}
    if op == "interview.finish":
        story = find(p["stories"], data["storyId"])
        require(story["topicId"] in TOPICS and sum(m["role"] == "user" for m in story["messages"]) == 4, "尚未完成四轮访谈")
        story["completed"] = True
        history_evidence(p, story)
        return {"storyId": story["id"], "completed": True}
    if op == "record.add":
        values = [text(data[k], k) for k in ("fact", "action", "context", "reflection")]
        labels = ["发生了什么", "实际做了什么", "角色、限制与感受", "当前解释与反例"]
        story = dict(id=uid(), topicId="recent", title="近期记录 · "+values[0][:40], completed=True, provider="skill", createdAt=now(),
                     messages=[dict(id=uid(), role="user", content=f"{label}：{v}", createdAt=now()) for label, v in zip(labels, values)])
        p["stories"].append(story)
        history_evidence(p, story)
        return {"sourceId": story["id"], "evidenceId": "story-"+story["id"]}
    if op == "correction.add":
        p.setdefault("reportFeedback", []).append(dict(finding=text(data["finding"], maximum=1800),
                                                       text=text(data["text"], maximum=600), createdAt=now()))
        return {"correctionRecorded": True}
    if op == "practice.create":
        cycle = {k: text(data[k], k, maximum=600) for k in ("question", "desired", "preserve", "context", "constraint")}
        require(data["capacity"] in ("light", "room"), "精力无效")
        require(isinstance(data["evidenceIds"], list) and set(data["evidenceIds"]) <= {e["id"] for e in p["evidence"]}, "行动依据无效")
        cycle.update(id=uid(), topic="custom", capacity=data["capacity"], evidenceIds=data["evidenceIds"], attempts=[], createdAt=now())
        p["practices"].append(cycle)
        return {"cycleId": cycle["id"]}
    if op == "practice.plan":
        cycle = find(p["practices"], data["cycleId"])
        last = cycle["attempts"][-1] if cycle["attempts"] else None
        require(last is None or "review" in last, "请先复盘当前尝试")
        if last and last["review"]["next"] == "pause":
            require(data.get("resume") is True, "用户此前暂停，需明确恢复后再创建尝试")
        validate_plan(data["plan"])
        plan = {k: text(data["plan"][k], maximum=600) for k in ("optionId", "title", "trigger", "action", "why", "observe", "stop", "prediction")}
        plan.update(id=uid(), createdAt=now())
        cycle["attempts"].append(plan)
        return {"attemptId": plan["id"]}
    if op == "practice.review":
        cycle = find(p["practices"], data["cycleId"])
        attempt = find(cycle["attempts"], data["attemptId"])
        require("review" not in attempt, "这次尝试已经复盘")
        validate_review(data["review"])
        review = {k: data["review"][k] for k in ("attempted", "actual", "learning", "next", "nextAction")}
        review["createdAt"] = now()
        attempt["review"] = review
        p["evidence"].append(dict(id=uid(), sourceId=cycle["id"], groupId=attempt["id"], sourceType="historical", context="life", pressure=False,
            title="行动复盘 · "+cycle["question"], observation="行动复盘自述；未尝试、部分尝试和已尝试必须区分，不产生人格假设。",
            quote=f'原动作：{attempt["action"]}\n事前预期：{attempt["prediction"]}\n尝试状态：{review["attempted"]}\n实际：{review["actual"]}\n解释：{review["learning"]}\n下一步：{review["nextAction"]}',
            hypotheses=[], createdAt=now()))
        return {"reviewRecorded": True, "next": review["next"]}
    if op == "source.delete":
        source = data["sourceId"]
        require(source == "baseline" or source in {r["id"] for key in ("runs", "stories", "practices") for r in p[key]}, "来源不存在")
        remove = {source}
        while True:
            eids = {e["id"] for e in p["evidence"] if e["sourceId"] in remove}
            derived = {c["id"] for c in p["practices"] if set(c["evidenceIds"]) & eids}
            if derived <= remove:
                break
            remove |= derived
        for key in ("runs", "stories", "practices"):
            p[key] = [r for r in p[key] if r["id"] not in remove]
        p["evidence"] = [e for e in p["evidence"] if e["sourceId"] not in remove]
        if source == "baseline":
            p["answers"], p["baselineCompleted"] = [], False
        p["reportFeedback"] = []
        # Discard retry results, which may contain the just-deleted raw material.
        p["_skill"]["requests"] = {}
        return {"removedSourceIds": sorted(remove), "correctionsCleared": True}
    if op == "report.save":
        check = validate_report(data["report"], p)
        p["_skill"]["report"] = copy.deepcopy(data["report"])
        return check
    raise ValueError("未知操作")


def load_profile(path):
    p = validate_profile(read_json(path))
    require("_skill" in p, "这是网站原始档案，请用 import 导入到新文件，原文件保持不变")
    # Never expose a stale report as current, including after hand edits.
    if p["_skill"].get("report", {}).get("inputDigest") not in (None, digest(p)):
        p["_skill"].pop("report", None)
    return p


def status(p):
    progress = readiness(p)
    return dict(revision=p["_skill"]["revision"], inputDigest=digest(p), demo=p["demo"],
        context=p["_skill"]["context"],
        baseline=dict(answered=progress["answered"], total=24, complete=progress["baselineComplete"],
                      remaining=[q for q in QUESTIONS if q not in {a["questionId"] for a in p["answers"]}]),
        scenarios=[dict(runId=r["id"], scenarioId=r["scenarioId"], answered=len(r["events"]), total=5,
                        currentNodeId=r["currentNodeId"], completed=r["completed"]) for r in p["runs"]],
        interviews=[dict(storyId=s["id"], topicId=s["topicId"], answered=sum(m["role"] == "user" for m in s["messages"]),
                         completed=s["completed"]) for s in p["stories"] if s["topicId"] != "recent"],
        completedScenarioTypes=progress["scenarioCount"], completedInterviewTopics=progress["completedStoryTopics"],
        practices=[dict(cycleId=c["id"], question=c["question"], attempts=len(c["attempts"]),
                        next=c["attempts"][-1].get("review", {}).get("next", "awaiting-review") if c["attempts"] else "awaiting-plan") for c in p["practices"]],
        evidenceRecords=len(p["evidence"]), evidenceGroups=len({e["groupId"] for e in p["evidence"]}),
        reportStatus=p["_skill"].get("report", {}).get("status", "not-current"),
        note="进度只表示已采集的材料数量；不表示人格准确率，也不限制提前分析。")


def public_node(p, run_id):
    r = find(p["runs"], run_id)
    scenario = SCENARIOS[r["scenarioId"]]
    base = dict(runId=r["id"], title=scenario["title"], role=scenario["role"], setting=scenario["setting"],
                state=r["state"], resources=scenario["resources"], completed=r["completed"], events=r["events"])
    if not r["completed"]:
        n = current_node(r, scenario)
        condition = n.get("conditional")
        base.update(nodeId=n["id"], round=len(r["events"])+1, title=n["title"], narrative=n["narrative"],
                    choices=[dict(id=c["id"], text=c["text"]) for c in n["choices"]],
                    information=[dict(id=i["id"], question=i["question"]) for i in n["availableInformation"]],
                    requests=r["pendingRequests"], freeformAllowed=n["freeformAllowed"],
                    conditional=condition["text"] if condition and r["state"][condition["resource"]] < condition["below"] else None)
    return base


def readable_model(p):
    model = aggregate(p["evidence"])
    rows = []
    for t in model["traits"]:
        d = DIMENSIONS[t["dimension"]]
        value = t["behavioralEstimate"]
        if value is None:
            observation = "只有一般自述，未形成情境观察" if t["selfReportEstimate"] is not None else "等待资料"
        else:
            observation = (d["high"] if value >= 55 else d["low"] if value <= 45 else "随条件调整")+"（暂定情境线索）"
        rows.append(dict(dimension=t["dimension"], name=d["name"], observation=observation,
                         description=d["description"], eventGroups=t["evidenceCount"],
                         contexts=list(dict.fromkeys(CATALOG["contextNames"][x["context"]] for x in t["contextEffects"])),
                         evidenceIds=t["evidence"], selfReportDiffers=bool(t["contradictions"])))
    return dict(dimensions=rows, corrections=p.get("reportFeedback", []),
                note="固定规则用于整理线索。经历、模拟与自述仍应分别解读；数字未做信效度校准。用户修正优先于自动标签。")


def markdown_text(value):
    value = html.escape(str(value), quote=False)
    for char in ("\\", "`", "*", "_", "[", "]", "|", "#"):
        value = value.replace(char, "\\"+char)
    return value.replace("\n", "<br>")


def render(p):
    """Render saved content without asking the model to restate or invent it."""
    esc = markdown_text
    progress = status(p)
    lines = ["# 自我模型 · 私人阅读版", "", "资料性质："+("虚构示例" if p["demo"] else "用户自述与记录，未经外部核实"),
             "", "这份文件包含私人资料，请只保存在自己的私人位置。", "", "## 进度与关注", "",
             f'基线 {progress["baseline"]["answered"]}/24 题；完整情境 {progress["completedScenarioTypes"]} 类；完整访谈 {progress["completedInterviewTopics"]} 类。', ""]
    for k, v in p["_skill"]["context"].items():
        label = {"goal": "想了解的问题", "preserve": "希望保留的东西", "constraints": "现实限制", "roles": "当前角色"}[k]
        lines.append(f'- {label}：{esc(v)}')
    lines += ["", "## 当前维度线索", "", "| 维度 | 暂定观察 | 事件组数 | 原始依据 |", "| --- | --- | --- | --- |"]
    for row in readable_model(p)["dimensions"]:
        lines.append(f'| {esc(row["name"])} | {esc(row["observation"])} | {row["eventGroups"]} | {esc("、".join(row["evidenceIds"]))} |')
    lines += ["", "以上由固定启发规则整理，不是人格测量分数；用户纠正与情境差异需一并阅读。"]
    if p.get("reportFeedback"):
        lines += ["", "## 用户修正", ""]
        for f in p["reportFeedback"]:
            lines += [f'- 原判断：{esc(f["finding"])}；修正：{esc(f["text"])}']
    report = p["_skill"].get("report")
    if report and report["inputDigest"] == digest(p):
        lines += ["", "## 整合报告"+("（草稿）" if report["status"] == "draft" else ""), "", esc(report["summary"])]
        for o in report["observations"]:
            lines += ["", f'### {esc(o["claim"])}', "", f'依据：{esc("、".join(o["evidenceIds"]))}',
                      "", f'适用条件：{esc(o["conditions"])}', "", f'另一种解释：{esc(o["alternative"])}', "", f'未知：{esc(o["unknown"])}']
        for person in report["people"]:
            field = {"science": "科学", "arts": "文学与艺术", "business": "商业", "engineering": "工程与设计", "healthcare": "医疗与护理", "education": "教育", "sports": "体育", "public-service": "公共事务", "humanities": "人文研究"}[person["field"]]
            verification = {"browsed": "已查阅公开来源", "provided": "基于用户提供的资料", "unverified": "尚未查阅来源，仅为候选"}[person["verification"]]
            lines += ["", f'### {esc(person["name"])} · {field}', "",
                      f'查阅状态：{verification}；个人依据：{esc("、".join(person["evidenceIds"]))}', "",
                      "关键差异："+esc("；".join(person["differences"]))]
            sources = {s["id"]: s for s in person["sources"]}
            for fact in person["facts"]:
                source = sources[fact["sourceId"]]
                url = source.get("url", "")
                citation = f'[{esc(source["title"])}]({quote(url, safe=":/?#=&%+-._~")})' if person["verification"] == "browsed" else esc(source["title"])+"（用户提供）"
                lines += ["", esc(fact["statement"])+" "+citation]
            path = person["path"]
            for k, label in (("direction", "可探索方向"), ("conditions", "前提"), ("benefit", "可能收益"), ("cost", "代价"), ("risk", "风险")):
                lines += ["", label+"："+esc(path[k])]
            lines += ["", "候选小尝试（不代表用户已决定执行）："]
            for k, label in (("trigger", "何时开始"), ("action", "具体做法"), ("why", "尝试理由"), ("observe", "观察什么"), ("stop", "何时停止")):
                lines.append(f'- {label}：{esc(path["experiment"][k])}')
        lines += ["", "### 路径比较", "", esc(report["comparison"]), "", "### 未知", ""]
        lines += ["- "+esc(v) for v in report["unknowns"]]
        review_kind = "独立复核" if report["review"]["kind"] == "independent-review" else "自查"
        lines += ["", f'复核方式：{review_kind}；{esc(report["review"]["notes"])}', "", "程序仅检查结构与引用内部一致性，不能验证事实或解释真伪。"]
    else:
        lines += ["", "尚无与当前资料对应的整合报告；旧报告不会作为当前结果导出。"]
    lines += ["", "## 行动与复盘", ""]
    for cycle in p["practices"]:
        lines += [f'### {esc(cycle["question"])}', ""]
        for attempt in cycle["attempts"]:
            lines += [f'- 计划：{esc(attempt["action"])}；事前预期：{esc(attempt["prediction"])}']
            if "review" in attempt:
                r = attempt["review"]
                attempted = {"yes": "已尝试", "partly": "部分尝试", "no": "未尝试"}[r["attempted"]]
                next_step = {"continue": "继续", "adjust": "调整", "pause": "暂停"}[r["next"]]
                lines += [f'- 状态：{attempted}；实际：{esc(r["actual"])}；解释：{esc(r["learning"])}；下一步：{next_step} / {esc(r["nextAction"])}']
            else:
                lines += ["- 尚无实际复盘，不能当作已执行。"]
    lines += ["", "## 原始依据", ""]
    for e in p["evidence"]:
        source_type = {"self_report": "一般自述", "historical": "经历与复盘自述", "simulated": "模拟选择", "reasoning": "选择理由"}[e["sourceType"]]
        lines += [f'### {esc(e["id"])}', "", f'{esc(e["title"])}（{source_type}，同组 {esc(e["groupId"])}）',
                  "", esc(e["observation"]), "", esc(e.get("quote", "没有原文引句")), ""]
    return "\n".join(lines)+"\n"


def apply(path, data, expected_revision):
    path = writable_path(path)
    require(isinstance(data, dict), "操作应为 JSON 对象")
    request_id = text(data["requestId"], "请求编号", maximum=150)
    payload_hash = hashlib.sha256(canonical(data).encode()).hexdigest()
    with Lock(path):
        p = load_profile(path)
        previous = p["_skill"]["requests"].get(request_id)
        if previous:
            require(previous["hash"] == payload_hash, "请求编号已用于其他内容；不要重复写入")
            return dict(replayed=True, result=previous["result"], **status(p))
        require(p["_skill"]["revision"] == expected_revision, "档案已经变化，请重新读取再更新；不会覆盖较新的记录")
        before = digest(p)
        p["updatedAt"] = now()
        result = operate(p, data)
        if digest(p) != before:
            p["_skill"].pop("report", None)
            p.pop("aiReport", None)
            for c in p["practices"]:
                c.pop("aiAdvice", None)
        p["_skill"]["revision"] += 1
        requests = p["_skill"]["requests"]
        requests[request_id] = dict(hash=payload_hash, result=result)
        # Bound retry metadata; deleting material clears it separately.
        while len(requests) > 100:
            del requests[next(iter(requests))]
        validate_profile(p)
        atomic_write(path, p)
        return dict(replayed=False, result=result, **status(p))


def initialize(path, demo=False, imported=None):
    path = writable_path(path)
    with Lock(path):
        require(not path.exists(), "目标文件已存在；不会覆盖现有档案")
        if imported is None:
            p = new_profile(demo)
        else:
            p = copy.deepcopy(validate_profile(imported))
            p["_skill"] = dict(format=2, revision=0, requests={}, context=copy.deepcopy(p.get("_skill", {}).get("context", {})))
            p.setdefault("practices", [])
            p.pop("aiReport", None)
            p.pop("fullAnalysisAccess", None)
            p["remoteAI"] = False
            for c in p["practices"]:
                c.pop("aiAdvice", None)
            p["updatedAt"] = now()
        validate_profile(p)
        atomic_write(path, p)
    return status(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("catalog", help="读取原题或主题目录")
    catalog.add_argument("--section", choices=("baseline", "scenarios", "topics", "dimensions"), required=True)
    catalog.add_argument("--start", type=int, default=1)
    catalog.add_argument("--count", type=int, default=4)
    for name in ("init", "import", "status", "show", "model", "apply", "report-check", "export"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--profile", required=True)
        if name == "init":
            cmd.add_argument("--demo", action="store_true")
        if name in ("import", "apply", "report-check"):
            cmd.add_argument("--input", required=True)
        if name == "apply":
            cmd.add_argument("--expected-revision", type=int, required=True)
        if name == "export":
            cmd.add_argument("--out", required=True)
        if name == "show":
            group = cmd.add_mutually_exclusive_group(required=True)
            group.add_argument("--run")
            group.add_argument("--story")
            group.add_argument("--evidence")
            group.add_argument("--dossier", action="store_true")
            group.add_argument("--report", action="store_true")
        if name == "model":
            cmd.add_argument("--technical", action="store_true", help="网站规则对照用，数值不是测量准确率")
    args = parser.parse_args()
    if args.command == "catalog":
        if args.section == "baseline":
            require(1 <= args.start <= 24 and 1 <= args.count <= 24, "题目范围无效")
            result = dict(scale={str(i+1): label for i, label in enumerate(LABELS)},
                          questions=[dict(id=q["id"], text=q["text"]) for q in CATALOG["baselineQuestions"][args.start-1:args.start-1+args.count]])
        elif args.section == "scenarios":
            result = [{k: s[k] for k in ("id", "title", "subtitle", "description", "role", "duration")} for s in SCENARIOS.values()]
        else:
            result = CATALOG["lifeTopics" if args.section == "topics" else "dimensions"]
    elif args.command == "init":
        result = initialize(args.profile, args.demo)
    elif args.command == "import":
        result = initialize(args.profile, imported=read_json(args.input))
    elif args.command == "apply":
        result = apply(args.profile, read_json(args.input), args.expected_revision)
    else:
        p = load_profile(args.profile)
        if args.command == "status":
            result = status(p)
        elif args.command == "model":
            result = aggregate(p["evidence"]) if args.technical else readable_model(p)
        elif args.command == "report-check":
            result = validate_report(read_json(args.input), p)
        elif args.command == "export":
            out = writable_path(args.out)
            with Lock(out):
                require(not out.exists(), "导出目标已存在，请指定新文件，不覆盖现有阅读版")
                atomic_write(out, render(p), as_text=True)
            result = {"exported": str(out), "inputDigest": digest(p), "note": "仅导出指定档案的当前资料；不会同步修改既有副本。"}
        elif args.run:
            result = public_node(p, args.run)
        elif args.story:
            result = find(p["stories"], args.story)
        elif args.evidence:
            result = find(p["evidence"], args.evidence)
        elif args.report:
            result = p["_skill"].get("report", {"status": "not-current"})
        else:
            # Explicit dossier output only; no identity, account, billing or retry metadata.
            result = {k: p.get(k, []) for k in ("answers", "runs", "stories", "evidence", "practices", "reportFeedback")}
            result.update(inputDigest=digest(p), demo=p["demo"], context=p["_skill"]["context"], progress=status(p))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # Avoid echoing arbitrary input content or secrets in parser errors.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "文件或资料格式无效；请检查字段和路径，原档案未被覆盖"
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
