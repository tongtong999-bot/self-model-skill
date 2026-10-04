"""Website-derived exploration rules. Numbers are heuristics, not psychometrics."""
import copy
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "data/catalog.json").read_text(encoding="utf-8"))
DIMENSIONS = {d["id"]: d for d in CATALOG["dimensions"]}
QUESTIONS = {q["id"]: q for q in CATALOG["baselineQuestions"]}
SCENARIOS = {s["id"]: s for s in CATALOG["scenarios"]}
TOPICS = {t["id"]: t for t in CATALOG["lifeTopics"]}
LABELS = ["非常不符合", "比较不符合", "不确定 / 居中", "比较符合", "非常符合"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, label="文字", minimum=1, maximum=4000):
    require(isinstance(value, str) and minimum <= len(value.strip()) <= maximum,
            f"{label}应为 {minimum}–{maximum} 字")
    return value.strip()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def uid():
    return str(uuid.uuid4())


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def jsround(value):
    return math.floor(value + 0.5)


def new_profile(demo=False):
    return dict(version=1, id=uid(), name="示例档案" if demo else "我的档案", demo=demo,
                onboarded=True, answers=[], baselineCompleted=False, runs=[], stories=[],
                evidence=[], remoteAI=False, practices=[], updatedAt=now(),
                _skill=dict(format=2, revision=0, requests={}, context={}))


def baseline_evidence(profile):
    result = []
    for a in profile["answers"]:
        q = QUESTIONS[a["questionId"]]
        value = 6-a["value"] if q.get("reverse") else a["value"]
        result.append(dict(id="baseline-"+q["id"], sourceType="self_report", sourceId="baseline",
                           groupId="baseline", title="自我认知基线", observation=q["text"],
                           quote=LABELS[a["value"]-1], context="baseline", pressure=False,
                           createdAt=profile["updatedAt"], hypotheses=[dict(
                               dimension=q["dimension"], direction=(value-3)/2, weight=1, confidence=0.5,
                               reason="用户对自身倾向的报告，尚未经行为证据验证。",
                               alternatives=["对题目的理解、近期状态与社会期待都可能影响回答。"])]))
    return result


def create_run(scenario):
    return dict(id=uid(), scenarioId=scenario["id"], currentNodeId=scenario["nodes"][0]["id"],
                state={r["id"]: r["initial"] for r in scenario["resources"]}, events=[],
                pendingRequests=[], completed=False, createdAt=now())


def current_node(run, scenario):
    require(not run["completed"], "此场景已完成")
    nodes = [n for n in scenario["nodes"] if n["id"] == run["currentNodeId"]]
    require(len(nodes) == 1, "无效节点")
    return nodes[0]


def request_information(run, scenario, information_id=None, custom_question=None):
    node = current_node(run, scenario)
    item = next((i for i in node["availableInformation"] if i["id"] == information_id), None)
    require(item is not None or bool(custom_question), "请选择信息或填写问题")
    if item and any(r["id"] == f'{node["id"]}-{item["id"]}' for r in run["pendingRequests"]):
        return run
    require(len(run["pendingRequests"]) < 12, "本轮最多保留 12 条信息请求")
    result = copy.deepcopy(run)
    result["pendingRequests"].append(dict(
        id=f'{node["id"]}-{item["id"]}' if item else uid(),
        question=item["question"] if item else text(custom_question),
        answer=item["answer"] if item else "现有情境资料无法回答这个问题。该信息缺口已记录，你可以在理由中说明它如何影响选择。",
        category=item["category"] if item else "自由提问", custom=item is None, requestedAt=now()))
    return result


def make_decision(run, scenario, data):
    node = current_node(run, scenario)
    choice = next((c for c in node["choices"] if c["id"] == data.get("choiceId")), None)
    require(choice is not None or data.get("choiceId") == "custom", "无效方案")
    custom = text(data.get("custom"), "自定方案", 5) if choice is None else ""
    reasoning = text(data.get("reasoning"), "理由", 8)
    require(data.get("priority") in DIMENSIONS, "请选择你最在意的因素")
    state = dict(run["state"])
    for key, value in (choice or {}).get("effects", {}).items():
        state[key] = clamp(state.get(key, 50)+value)
    consequence = choice["consequence"] if choice else "自定义方案已记录。演示模式无法可靠推演自由方案的资源后果，因此资源保持原值；接下来呈现共同的外部事件。"
    event = dict(id=uid(), nodeId=node["id"], choiceId=data["choiceId"],
                 choiceText=choice["text"] if choice else custom, reasoning=reasoning,
                 priority=data["priority"], requests=copy.deepcopy(run["pendingRequests"]),
                 stateBefore=dict(run["state"]), stateAfter=state, consequence=consequence, createdAt=now())
    if data.get("prediction"):
        event["prediction"] = text(data["prediction"], "事前预期", maximum=600)
    hypotheses = copy.deepcopy(choice["hypotheses"] if choice else [])
    n = len(event["requests"])
    if n:
        hypotheses.append(dict(dimension="information", direction=min(.95, .18+n*.17),
                               weight=.7, confidence=.7, reason=f"决策前主动请求 {n} 项信息。",
                               alternatives=["可能因为不熟悉场景或好奇界面内容；信息数量不等于信息质量。"] ))
    if node["irreversible"] and n >= 3:
        hypotheses.append(dict(dimension="action", direction=-.65, weight=.55, confidence=.55,
                               reason="面对难以撤回的选择，先查看多项信息再提交决定。",
                               alternatives=["未测量决策速度；这仅支持此处较审慎的行动顺序，不能断言拖延。"] ))
    base = dict(sourceId=run["id"], groupId=event["id"], context=scenario["context"],
                pressure=node["pressure"], createdAt=event["createdAt"], quote=reasoning)
    evidence = [dict(base, id=uid(), sourceType="simulated", title=f'{scenario["title"]} · {node["title"]}',
                     observation=f'先请求 {n} 项信息，随后选择「{event["choiceText"]}」。', hypotheses=hypotheses),
                dict(base, id=uid(), sourceType="reasoning", title=f'选择理由 · {node["title"]}',
                     observation=f'用户将「{DIMENSIONS[data["priority"]]["name"]}」选为本轮最在意的因素。',
                     hypotheses=[dict(dimension=data["priority"], direction=.55, weight=.28, confidence=.4,
                                      reason="用户主动说明的权衡因素，属于解释性自述。",
                                      alternatives=["说明的理由可能不完整，也可能带有事后合理化；不能当作独立行为验证。"] )])]
    index = scenario["nodes"].index(node)
    next_id = (choice or {}).get("nextNode") or (scenario["nodes"][index+1]["id"] if index+1 < len(scenario["nodes"]) else None)
    result = copy.deepcopy(run)
    result.update(state=state, events=run["events"]+[event], pendingRequests=[],
                  currentNodeId=next_id, completed=next_id is None)
    return result, evidence


def aggregate(evidence):
    """Port of website engine: group dependent evidence and cap each source's mass."""
    traits = []
    for d in CATALOG["dimensions"]:
        items = [(e, h) for e in evidence for h in e["hypotheses"] if h["dimension"] == d["id"]]
        selfs = [h for e, h in items if e["sourceType"] == "self_report"]
        self_est = jsround(50+50*sum(h["direction"] for h in selfs)/len(selfs)) if selfs else None
        groups = {}
        for e, h in items:
            if e["sourceType"] != "self_report":
                groups.setdefault(e["groupId"], []).append((e, h))
        clusters = []
        for group in groups.values():
            total = sum(h["weight"]*h["confidence"] for e, h in group)
            e = group[0][0]
            clusters.append(dict(direction=sum(h["direction"]*h["weight"]*h["confidence"] for e, h in group)/total if total else 0,
                                 weight=min(.8, max(h["weight"]*h["confidence"] for e, h in group)),
                                 context=e["context"], pressure=e["pressure"], source=e["sourceId"]))
        mass = {}
        for c in clusters:
            mass[c["source"]] = mass.get(c["source"], 0)+c["weight"]
        for c in clusters:
            c["weight"] *= min(1, 1.5/(mass[c["source"]] or 1))
        weight = sum(c["weight"] for c in clusters)
        mean = sum(c["direction"]*c["weight"] for c in clusters)/weight if weight else 0
        behavior = jsround(50+50*mean*weight/(.65+weight)) if weight else None
        contexts = list(dict.fromkeys(c["context"] for c in clusters))
        variance = sum(c["weight"]*(c["direction"]-mean)**2 for c in clusters)/weight if weight else 0
        consistency = clamp(1-math.sqrt(variance), 0, 1)
        cap = .34 if len(contexts) <= 1 else .62 if len(contexts) == 2 else .85
        confidence = min(cap, (1-math.exp(-weight/2))*(.6+.4*consistency)) if weight else 0
        effects = []
        for context, pressure in dict.fromkeys((c["context"], c["pressure"]) for c in clusters):
            cs = [c for c in clusters if (c["context"], c["pressure"]) == (context, pressure)]
            w = sum(c["weight"] for c in cs)
            effects.append(dict(context=context, pressure=pressure, count=len(cs),
                                estimate=jsround(50+50*sum(c["direction"]*c["weight"] for c in cs)/(.65+w))))
        means = []
        for context in contexts:
            cs = [c for c in clusters if c["context"] == context]
            w = sum(c["weight"] for c in cs)
            means.append(sum(c["direction"]*c["weight"] for c in cs)/w if w else 0)
        stability = clamp(1-(max(means)-min(means))/2, 0, 1) if len(contexts) >= 2 else None
        ids = list(dict.fromkeys(e["id"] for e, h in items))
        contradictions = []
        if self_est is not None and behavior is not None and abs(self_est-behavior) >= 18 and len(clusters) >= 3 and confidence >= .35 and len(contexts) >= 2:
            gap = jsround(self_est-behavior)
            special = d["id"] == "action" and gap > 0 and self_est >= 60
            contradictions.append(dict(dimension=d["id"], gap=gap,
                title="你的果断，可能有它的条件" if special else f'{d["name"]}：自述与情境观察有所不同',
                description="你认为自己做决定较快。在多个难以撤回的情境中，你先请求多项信息再行动。这可能说明：信息不足时，你更重视确认条件。这里没有测量真实用时，仍需要现实经历验证。" if special else f"自我报告为 {self_est}，目前情境与经历证据的探索性估计为 {behavior}。差异可能来自情境约束、题目理解或真实偏好变化，需要继续核对，而非判定哪一方“更真实”。",
                evidenceIds=ids))
        traits.append(dict(dimension=d["id"], estimate=behavior if behavior is not None else self_est,
                           confidence=confidence, evidenceCount=len(groups), selfReportEstimate=self_est,
                           behavioralEstimate=behavior, consistency=consistency, crossContextStability=stability,
                           contextEffects=effects, evidence=ids, contradictions=contradictions))
    return dict(traits=traits, confidence=sum(t["confidence"] for t in traits)/len(traits),
                contradictions=sorted([c for t in traits for c in t["contradictions"]], key=lambda c: -abs(c["gap"])),
                evidenceCount=len(evidence), contextCount=len({e["context"] for e in evidence if e["sourceType"] != "self_report"}))


def readiness(profile):
    answered = {a["questionId"] for a in profile["answers"] if a["questionId"] in QUESTIONS and type(a["value"]) is int and 1 <= a["value"] <= 5}
    complete = profile["baselineCompleted"] and len(answered) == len(QUESTIONS)
    runs = {r["scenarioId"] for r in profile["runs"] if r["scenarioId"] in SCENARIOS and r["completed"]
            and all(any(e["nodeId"] == n["id"] for e in r["events"]) for n in SCENARIOS[r["scenarioId"]]["nodes"])
            and all(len(e["reasoning"].strip()) >= 8 for e in r["events"])
            and any(e["sourceId"] == r["id"] and e["sourceType"] == "simulated" for e in profile["evidence"])}
    stories = {s["topicId"] for s in profile["stories"] if s["topicId"] in TOPICS and s["completed"]
               and len([m for m in s["messages"] if m["role"] == "user" and len(m["content"].strip()) >= 8]) >= 4
               and any(e["sourceId"] == s["id"] and e["sourceType"] == "historical" for e in profile["evidence"])}
    nr, ns = min(3, len(runs)), min(3, len(stories))
    score = (20 if complete else min(19, 20*len(answered)/24))+(25+(nr-1)*10 if nr else 0)+(20+(ns-1)*7.5 if ns else 0)
    return dict(answered=len(answered), baselineComplete=complete, scenarioCount=nr, storyCount=ns,
                completedStoryTopics=len(stories), websiteCollectionProgress=jsround(score*10)/10,
                websiteReady=bool(complete and nr and ns and score >= 60))
