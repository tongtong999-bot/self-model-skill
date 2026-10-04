"""Only synthetic records; tests never read personal profiles or API credentials."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/self-model/scripts"))
import model as m
import self_model as sm


def projected(model):
    return [{**{k: v for k, v in t.items() if k not in ("evidence", "contradictions")},
             "contradictionGaps": [c["gap"] for c in t["contradictions"]]} for t in model["traits"]]


def synthetic_report(p, complete=False):
    people = []
    for index, field in enumerate(("science", "arts", "business")):
        people.append(dict(id=f"p{index}", name=f"虚构测试人物{index}", field=field,
            evidenceIds=[p["evidence"][0]["id"]], differences=["测试差异一", "测试差异二"],
            verification="provided" if complete else "unverified",
            sources=[dict(id="s1", title="虚构测试资料", text="测试人物完成了一份作品。", accessedAt="测试提供")] if complete else [],
            facts=[dict(id="f1", statement="测试人物完成作品。", sourceId="s1", quote="完成了一份作品")] if complete else [],
            path=dict(direction="测试方向", conditions="用户以后选择时", benefit="可能得到反馈", cost="少量时间", risk="可能不适用",
                      experiment=dict(trigger="有余力时", action="记录一个片段", why="区分两种解释", observe="是否发生", stop="用户暂停时停止"))))
    return dict(inputDigest=sm.digest(p), status="complete" if complete else "draft", summary="合成测试，不是真实人物分析。",
        observations=[dict(id="o1", claim="待检验解释", conditions="这个情境中", alternative="资源约束", unknown="其他情境未知", evidenceIds=[p["evidence"][0]["id"]])],
        people=people, comparison="三种测试方案，均非现实建议。", unknowns=["测试资料有限"], review=dict(kind="self-review", notes="仅用来测试结构，不验证事实。"))


class WebsiteParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = json.loads((ROOT / "tests/fixtures/website-reference.json").read_text())

    def near(self, left, right):
        if isinstance(right, dict):
            self.assertEqual(left.keys(), right.keys())
            for k in right:
                self.near(left[k], right[k])
        elif isinstance(right, list):
            self.assertEqual(len(left), len(right))
            for a, b in zip(left, right):
                self.near(a, b)
        elif type(right) in (float, int):
            self.assertAlmostEqual(left, right, places=12)
        else:
            self.assertEqual(left, right)

    def test_original_baseline_and_reverse_items(self):
        p = m.new_profile(True)
        p["answers"] = self.ref["baselineAnswers"]
        p["baselineCompleted"] = True
        p["evidence"] = m.baseline_evidence(p)
        self.near(projected(m.aggregate(p["evidence"])), self.ref["baselineModel"])
        r = m.readiness(p)
        self.assertEqual(r["websiteCollectionProgress"], self.ref["baselineReadiness"]["score"])
        self.assertEqual(r["websiteReady"], self.ref["baselineReadiness"]["eligible"])

    def test_all_fixed_options_custom_options_and_aggregation(self):
        for path in self.ref["paths"]:
            with self.subTest(scenario=path["scenarioId"], first=path["steps"][0]["input"]["choiceId"]):
                p = m.new_profile(True)
                p["answers"] = self.ref["baselineAnswers"]
                evidence = m.baseline_evidence(p)
                scenario = m.SCENARIOS[path["scenarioId"]]
                run = m.create_run(scenario)
                for step in path["steps"]:
                    for information in step["requests"]:
                        run = m.request_information(run, scenario, information)
                    run, added = m.make_decision(run, scenario, step["input"])
                    self.near(run["state"], step["state"])
                    self.assertEqual(run["events"][-1]["consequence"], step["consequence"])
                    self.assertEqual(run["currentNodeId"], step["currentNodeId"])
                    self.assertEqual(run["completed"], step["completed"])
                    self.near([{k: e[k] for k in ("sourceType", "context", "pressure", "hypotheses")} for e in added], step["evidence"])
                    evidence.extend(added)
                self.near(projected(m.aggregate(evidence)), path["model"])

    def test_multiple_contexts_collection_counts_and_caps(self):
        p = m.new_profile(True)
        p["answers"] = self.ref["baselineAnswers"]
        p["baselineCompleted"] = True
        p["evidence"] = m.baseline_evidence(p)
        for scenario_id in m.SCENARIOS:
            path = next(r for r in self.ref["paths"] if r["scenarioId"] == scenario_id)
            scenario = m.SCENARIOS[scenario_id]
            run = m.create_run(scenario)
            for step in path["steps"]:
                for info in step["requests"]:
                    run = m.request_information(run, scenario, info)
                run, added = m.make_decision(run, scenario, step["input"])
                p["evidence"].extend(added)
            p["runs"].append(run)
        story = dict(id="synthetic-story", topicId="unknown", completed=True,
                     messages=[dict(role="user", content="这是一段足够长度的合成经历回答，不涉及真实用户。") for _ in range(4)])
        p["stories"].append(story)
        p["evidence"].append(dict(id="synthetic-history", sourceId=story["id"], groupId=story["id"],
                                 sourceType="historical", context="life", pressure=False, hypotheses=[]))
        self.near(projected(m.aggregate(p["evidence"])), self.ref["mixed"]["model"])
        progress = m.readiness(p)
        self.assertEqual(progress["websiteCollectionProgress"], self.ref["mixed"]["readiness"]["score"])
        self.assertEqual(progress["websiteReady"], self.ref["mixed"]["readiness"]["eligible"])


class Runtime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="self-model-test-")
        self.path = Path(self.tmp.name) / "profile.json"
        sm.initialize(self.path, demo=True)

    def tearDown(self):
        self.tmp.cleanup()

    def p(self):
        return sm.load_profile(self.path)

    def apply(self, op, **kwargs):
        return sm.apply(self.path, dict(requestId=m.uid(), op=op, **kwargs), self.p()["_skill"]["revision"])

    def record(self):
        return self.apply("record.add", fact="虚构测试：我推迟了写作。", action="当天只是挑选软件，没有开始写。",
                          context="可用时间有限，这是合成资料。", reflection="可能是目标不清楚，也可能是临时没有精力。")

    def cycle(self):
        self.record()
        result = self.apply("practice.create", question="能否开始一个段落", desired="了解启动条件", preserve="照护安排", context="虚构处境",
                            constraint="每周时间有限", capacity="light", evidenceIds=[self.p()["evidence"][0]["id"]])
        return result["result"]["cycleId"]

    def plan(self, cycle, **kwargs):
        return self.apply("practice.plan", cycleId=cycle,
            plan=dict(optionId="o1", title="写一个段落", trigger="有五分钟可用时", action="写第一句话", why="观察能否开始",
                      observe="是否实际启动", stop="照护需要出现时", prediction="用户未提供，暂不确定"), **kwargs)["result"]["attemptId"]

    def test_init_never_overwrites(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            sm.initialize(self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_partial_baseline_skip_is_not_neutral_or_complete(self):
        self.apply("baseline.answer", answers=[dict(questionId="b1", value=4)])
        self.assertEqual(sm.status(self.p())["baseline"]["remaining"][0], "b2")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.apply("baseline.finish")
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(ValueError):
            self.apply("baseline.answer", answers=[dict(questionId="b2", value=True)])

    def test_explicit_finish_and_duplicate_baseline_answer(self):
        self.apply("baseline.answer", answers=[dict(questionId=q, value=3) for q in m.QUESTIONS])
        self.assertFalse(m.readiness(self.p())["baselineComplete"])
        self.apply("baseline.finish")
        self.apply("baseline.answer", answers=[dict(questionId="b1", value=5)])
        self.assertEqual(len(self.p()["answers"]), 24)
        self.assertEqual(len(self.p()["evidence"]), 24)

    def test_revision_and_retry_protection(self):
        data = dict(requestId="fixed", op="scenario.start", scenarioId="flood")
        first = sm.apply(self.path, data, 0)
        retry = sm.apply(self.path, data, 0)
        self.assertTrue(retry["replayed"])
        self.assertEqual(first["result"], retry["result"])
        self.assertEqual(len(self.p()["runs"]), 1)
        with self.assertRaises(ValueError):
            sm.apply(self.path, dict(data, scenarioId="startup"), 1)
        with self.assertRaises(ValueError):
            sm.apply(self.path, dict(data, requestId="new"), 0)

    def test_information_and_no_spoilers_or_invented_custom_answer(self):
        run = self.apply("scenario.start", scenarioId="flood")["result"]["runId"]
        view = sm.public_node(self.p(), run)
        self.assertNotIn("answer", view["information"][0])
        self.assertNotIn("effects", view["choices"][0])
        args = dict(runId=run, nodeId=view["nodeId"], informationId=view["information"][0]["id"])
        self.apply("scenario.request", **args)
        self.apply("scenario.request", **args)
        self.assertEqual(len(self.p()["runs"][0]["pendingRequests"]), 1)
        custom = self.apply("scenario.request", runId=run, nodeId=view["nodeId"], question="明天一定晴天吗？")
        self.assertIn("无法回答", custom["result"]["requests"][-1]["answer"])
        self.apply("scenario.decide", runId=run, nodeId=view["nodeId"], choiceId="custom", custom="先提出我自己的方案", reasoning="合成测试理由，保留未知并尽量小范围尝试。", priority="reversibility")
        self.assertEqual(view["state"], self.p()["runs"][0]["state"])
        self.assertEqual(len({e["groupId"] for e in self.p()["evidence"]}), 1)

    def test_tampered_scenario_state_rejected(self):
        self.apply("scenario.start", scenarioId="startup")
        p = self.p()
        key = next(iter(p["runs"][0]["state"]))
        p["runs"][0]["state"][key] += 1
        with self.assertRaises(ValueError):
            sm.validate_profile(p)

    def test_interview_resume_four_rounds_one_event(self):
        story = self.apply("interview.start", topicId="unknown")["result"]["storyId"]
        for i in range(1, 5):
            self.apply("interview.answer", storyId=story, round=i, answer="这是合成的经历回答，有角色约束和未知信息。", nextQuestion="当时有哪些其他选择？")
            self.assertEqual(sm.status(self.p())["interviews"][0]["answered"], i)
        self.assertTrue(self.p()["stories"][0]["completed"])
        self.assertEqual(len(self.p()["evidence"]), 1)
        self.assertEqual(m.readiness(self.p())["completedStoryTopics"], 1)

    def test_plan_review_pause_and_explicit_resume(self):
        cycle = self.cycle()
        attempt = self.plan(cycle)
        with self.assertRaises(ValueError):
            self.plan(cycle)
        self.apply("practice.review", cycleId=cycle, attemptId=attempt,
                   review=dict(attempted="no", actual="照护占用了时间，没有尝试。", learning="这次不能验证写作预测。", next="pause", nextAction="先暂停一周。"))
        with self.assertRaises(ValueError):
            self.plan(cycle)
        self.plan(cycle, resume=True)
        self.assertEqual(len(self.p()["practices"][0]["attempts"]), 2)
        self.assertEqual(self.p()["evidence"][-1]["hypotheses"], [])

    def test_report_references_quotes_fields_and_staleness(self):
        self.record()
        report = synthetic_report(self.p(), complete=True)
        checked = sm.validate_report(report, self.p())
        self.assertFalse(checked["truthVerifiedByProgram"])
        for change in ("id", "quote", "field", "digest", "unverified"):
            bad = copy.deepcopy(report)
            if change == "id": bad["observations"][0]["evidenceIds"] = ["invented"]
            if change == "quote": bad["people"][0]["facts"][0]["quote"] = "来源里没有的话"
            if change == "field": bad["people"][1]["field"] = "science"
            if change == "digest": bad["inputDigest"] = "old"
            if change == "unverified": bad["people"][0]["verification"] = "unverified"
            with self.subTest(change=change), self.assertRaises(ValueError):
                sm.validate_report(bad, self.p())
        self.apply("report.save", report=report)
        self.assertEqual(sm.status(self.p())["reportStatus"], "complete")
        self.apply("correction.add", finding="我害怕所有风险", text="这个解释不对。")
        self.assertEqual(sm.status(self.p())["reportStatus"], "not-current")
        with self.assertRaises(ValueError):
            self.apply("report.save", report=report)

    def test_delete_cascades_into_derived_plans_and_retry_cache(self):
        cycle = self.cycle()
        self.plan(cycle)
        source = self.p()["stories"][0]["id"]
        self.apply("report.save", report=synthetic_report(self.p()))
        result = self.apply("source.delete", sourceId=source)
        self.assertIn(cycle, result["result"]["removedSourceIds"])
        p = self.p()
        self.assertFalse(p["stories"] or p["evidence"] or p["practices"])
        self.assertNotIn("推迟了写作", self.path.read_text())
        self.assertEqual(len(p["_skill"]["requests"]), 1)
        self.assertNotIn("report", p["_skill"])

    def test_import_keeps_original_demo_and_drops_derived_ai_report(self):
        self.record()
        p = self.p()
        p.pop("_skill")
        p["aiReport"] = {"private": "stale text"}
        target = self.path.with_name("imported.json")
        before = self.path.read_bytes()
        sm.initialize(target, imported=p)
        self.assertTrue(sm.load_profile(target)["demo"])
        self.assertNotIn("aiReport", sm.load_profile(target))
        self.assertEqual(before, self.path.read_bytes())

    def test_malformed_json_and_symbolic_link_cannot_overwrite(self):
        broken = self.path.with_name("broken.json")
        broken.write_text('{"x":1,"x":2}')
        with self.assertRaises(ValueError):
            sm.read_json(broken)
        link = self.path.with_name("link.json")
        link.symlink_to(self.path)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            sm.initialize(link)
        self.assertEqual(before, self.path.read_bytes())
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_parallel_writers_do_not_lose_updates(self):
        processes = []
        for i in range(2):
            payload = self.path.with_name(f"op{i}.json")
            payload.write_text(json.dumps(dict(requestId=f"parallel{i}", op="baseline.answer", answers=[dict(questionId=f"b{i+1}", value=4)])))
            processes.append(subprocess.Popen([sys.executable, str(ROOT/"skills/self-model/scripts/self_model.py"), "apply", "--profile", str(self.path), "--input", str(payload), "--expected-revision", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        outcomes = [p.communicate() for p in processes]
        self.assertEqual(sorted(p.returncode for p in processes), [0, 2])
        self.assertEqual(len(self.p()["answers"]), 1)
        self.assertFalse(self.path.with_name(self.path.name+".lock").exists())

    def test_readable_export_preserves_pause_and_escapes_embedded_markup(self):
        cycle = self.cycle()
        attempt = self.plan(cycle)
        self.apply("practice.review", cycleId=cycle, attemptId=attempt,
                   review=dict(attempted="no", actual="尚未尝试", learning="无法判断效果", next="pause", nextAction="先暂停"))
        self.apply("context.set", context={"goal": "![tracking](https://example.org/a.png)<script>alert(1)</script>"})
        p = self.p()
        output = sm.render(p)
        self.assertIn("下一步：暂停", output)
        self.assertNotIn("<script>", output)
        self.assertNotIn("![tracking]", output)
        self.assertIn("原始依据", output)
        out = self.path.with_name("reading.md")
        command = [sys.executable, str(ROOT/"skills/self-model/scripts/self_model.py"), "export", "--profile", str(self.path), "--out", str(out)]
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(out.read_text(), output)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
