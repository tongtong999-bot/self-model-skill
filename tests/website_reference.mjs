// Run with the website's tsx loader and cwd. Reads code only; no env/model/network.
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

const app = process.argv[2];
if (!app) throw new Error('Pass the original website directory.');
const fromApp = p => import(pathToFileURL(resolve(app, p)).href);
const { baselineQuestions } = await fromApp('src/data/baseline.ts');
const { dimensions, contextNames } = await fromApp('src/data/dimensions.ts');
const { scenarios, lifeTopics } = await fromApp('src/data/scenarios.ts');
const { createProfile, createRun, requestInformation, makeDecision, baselineEvidence, aggregate } = await fromApp('src/lib/engine.ts');
const { analysisReadiness } = await fromApp('src/lib/full-analysis.ts');
const baseline = createProfile(true);
baseline.answers = baselineQuestions.map((q, i) => ({questionId:q.id,value:i%5+1}));
baseline.baselineCompleted = true;
baseline.evidence = baselineEvidence(baseline);
const projection = model => model.traits.map(t => {
  const { evidence, contradictions, ...rest } = t;
  return { ...rest, contradictionGaps: contradictions.map(c => c.gap) };
});
const slimEvidence = e => ({sourceType:e.sourceType, context:e.context,pressure:e.pressure,hypotheses:e.hypotheses});
const paths = [];
const mixed = structuredClone(baseline);
mixed.runs = [];
for (const scenario of scenarios) {
  // Each possible option at each node is covered, plus custom choices and varied information requests.
  const max = Math.max(...scenario.nodes.map(n=>n.choices.length));
  for(let variant=0; variant<=max; variant++) {
    let run = createRun(scenario), evidence = structuredClone(baseline.evidence), steps=[];
    for(let i=0;i<scenario.nodes.length;i++) {
      const node=scenario.nodes[i];
      const requests=node.availableInformation.slice(0, (variant+i)%(node.availableInformation.length+1)).map(x=>x.id);
      for(const id of requests) run=requestInformation(run,scenario,id);
      const input={choiceId:variant===max?'custom':node.choices[variant%node.choices.length].id,
        custom:'这是虚构测试自定方案，只用于比较固定规则。',reasoning:'这是合成的测试理由，我会结合资源约束与信息可靠性再决定。',
        priority:dimensions[(variant+i)%dimensions.length].id,prediction:'预期用于演练对照，不是现实预测。'};
      const next=makeDecision(run,scenario,input);
      run=next.run; evidence.push(...next.evidence);
      steps.push({requests,input,state:run.state,consequence:run.events.at(-1).consequence,
        currentNodeId:run.currentNodeId,completed:run.completed,evidence:next.evidence.map(slimEvidence)});
    }
    paths.push({scenarioId:scenario.id,steps,model:projection(aggregate(evidence))});
    if (variant===0) {
      mixed.runs.push(run);
      mixed.evidence.push(...evidence.filter(e=>e.sourceType!=='self_report'));
    }
  }
}
const sourceFiles=['src/data/baseline.ts','src/data/dimensions.ts','src/data/scenarios.ts','src/lib/engine.ts','src/lib/full-analysis.ts'];
const hashes=Object.fromEntries(sourceFiles.map(p=>[p,createHash('sha256').update(readFileSync(resolve(app,p))).digest('hex')]));
const storyId='synthetic-story';
mixed.stories=[{id:storyId,topicId:'unknown',title:'虚构测试访谈',completed:true,provider:'mock',createdAt:'2026-10-04T00:00:00Z',
  messages:Array.from({length:4},(_,i)=>({id:`answer-${i}`,role:'user',content:'这是一段足够长度的合成经历回答，不涉及真实用户。',createdAt:'2026-10-04T00:00:00Z'}))}];
mixed.evidence.push({id:'synthetic-history',sourceId:storyId,groupId:storyId,sourceType:'historical',context:'life',pressure:false,
  title:'虚构经历',observation:'合成材料，仅用于规则对照。',quote:'这是一段虚构回答。',hypotheses:[],createdAt:'2026-10-04T00:00:00Z'});
console.log(JSON.stringify({note:'Synthetic reference outputs from the original website, no private data or model API calls.',hashes,
  catalog:{version:1,baselineQuestions,dimensions,contextNames,scenarios,lifeTopics},
  baselineAnswers:baseline.answers,baselineModel:projection(aggregate(baseline.evidence)),
  baselineReadiness:analysisReadiness(baseline),paths,
  mixed:{model:projection(aggregate(mixed.evidence)),readiness:analysisReadiness(mixed)}}));
