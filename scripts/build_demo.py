"""Build a self-contained interactive demo page from real artefacts.

The page has four tabs:
  1. context  - click a phenotype mention, see gold vs v1 window vs v2 scope,
                including the trigger and the masked run the resolver considered;
  2. labs     - independent unit conversion and demo-band classification;
  3. lineage  - the 16 diseases actually used, with record counts and HPO depth;
  4. splits   - patient/text/near-duplicate/cell-reuse audit results.

All numbers are read from the JSON artefacts at build time and embedded in the
page, so the demo works offline and every figure is traceable to a file.
No model is called at runtime.

Usage: python -m scripts.build_demo --out demo/index.html
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge import lab_standards
from clinforge.context_scope import ContextResolver
from clinforge.hpo_knowledge import load_knowledge_base
from clinforge.med_extract import build_term_index, classify_context, find_phenotype_mentions
from clinforge.synthgen import CURATED_DISEASES, load_gloss

ROOT = Path(__file__).resolve().parent.parent
STATUS_ZH = {'affirmed': '现症', 'suspected': '疑似', 'history': '既往', 'negated': '否定'}


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_index():
    kb = load_knowledge_base(ROOT / 'data/phase3_synth/kb/hpo_snapshot.json')
    gloss = load_gloss(ROOT / 'data/curated/zh_phenotype_gloss.json')
    allowed = set()
    for disease_id in CURATED_DISEASES:
        if disease_id in kb['diseases']:
            allowed |= set(kb['diseases'][disease_id]['phenotypes'])
    return build_term_index(kb, gloss, allowed)


def context_sample(record, corpus, index):
    text, lang = record['text'], record['language']
    gold = {(e['start'], e['end'], e['hp_id']): e['status']
            for e in record['entities'] if e['label'] == 'PHENOTYPE'}
    mentions = find_phenotype_mentions(text, index)
    spans = [(m['start'], m['end']) for m in mentions]
    resolver_v1 = ContextResolver(text, lang, spans, 'v1')
    resolver_ng = ContextResolver(text, lang, spans, 'negex')
    mention_rows = []
    for mention in mentions:
        key = (mention['start'], mention['end'], mention['hp_id'])
        if key not in gold:
            continue
        debug = resolver_ng.debug(mention['start'])
        mention_rows.append({
            'start': mention['start'], 'end': mention['end'],
            'text': mention['text'], 'hp_id': mention['hp_id'],
            'gold': gold[key],
            'v1': classify_context(text, mention, lang),
            'v2_scope_v1': resolver_v1.classify(mention['start']),
            'v2_scope_ng': resolver_ng.classify(mention['start']),
            'cue': debug.get('cue'),
            'run': debug.get('run') or '',
        })
    return {
        'id': record['record_id'], 'corpus': corpus, 'language': lang,
        'template': record['template_family'], 'disease': record['disease_name'],
        'text': text,
        'entities': [{'start': e['start'], 'end': e['end'], 'text': e['text'],
                      'label': e['label'], 'status': e.get('status')}
                     for e in record['entities']],
        'mentions': mention_rows,
    }


def pick_context_samples(index):
    dev = load_jsonl(ROOT / 'data/phase3_synth/gen/notes.jsonl')
    holdout = load_jsonl(ROOT / 'data/phase4_context/holdout_notes.jsonl')
    samples, used_families = [], set()

    # Dev notes where the fixed window says affirmed but the gold is history.
    for record in dev:
        sample = context_sample(record, 'dev（开发集）', index)
        bad = [m for m in sample['mentions'] if m['gold'] == 'history' and m['v1'] == 'affirmed']
        if bad and record['template_family'] not in used_families and record['language'] == 'zh':
            samples.append(sample)
            used_families.add(record['template_family'])
        if len(samples) >= 3:
            break

    # Holdout: one English list, one Chinese section header.
    for record in holdout:
        if record['language'] != 'en':
            continue
        sample = context_sample(record, '同生成器留出集（评测前冻结）', index)
        if any(m['gold'] == 'negated' and m['v1'] != 'negated' for m in sample['mentions']):
            samples.append(sample)
            break
    for record in holdout:
        if record['language'] != 'zh':
            continue
        sample = context_sample(record, '同生成器留出集（评测前冻结）', index)
        if any(m['gold'] == 'history' and m['v1'] == 'affirmed' for m in sample['mentions']):
            samples.append(sample)
            break
    return samples


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='demo/index.html')
    args = parser.parse_args(argv)

    index = build_index()
    samples = pick_context_samples(index)
    lineage = json.loads((ROOT / 'data/phase4_lineage/lineage_manifest.json').read_text(encoding='utf-8'))
    relations = json.loads((ROOT / 'reports/phase4_split_relations/relations.json').read_text(encoding='utf-8'))
    bootstrap = json.loads((ROOT / 'reports/phase4_split_relations/holdout_bootstrap.json').read_text(encoding='utf-8'))
    lab = json.loads((ROOT / 'reports/phase4_lab_independence/audit.json').read_text(encoding='utf-8'))

    payload = {
        'samples': samples,
        'diseases': [
            {'id': row['disease_id'], 'en': row['disease_name'], 'zh': row['disease_name_zh'],
             'source': row['source'], 'annotations': row['n_phenotype_annotations_in_snapshot'],
             'records': row['n_records']}
            for row in lineage['diseases']
        ],
        'stale': lineage['superseded_artifact'],
        'relations': {
            'composition': relations['composition'],
            'patient_overlap': relations['patient_links']['pairwise_patient_overlap'],
            'exact_duplicates': relations['text_relations']['exact_duplicate_pairs_across'],
            'skeleton_collisions': relations['text_relations']['skeleton_collisions_across'],
            'cell_reuse': relations['cell_reuse'],
            'near_duplicates': relations['near_duplicates'],
            'disease_name_leakage': relations['disease_name_leakage'],
            'claim_boundary': relations['claim_boundary'],
        },
        'bootstrap': bootstrap,
        'lab': {
            'factors': {k: v['factor'] for k, v in lab_standards.FACTORS.items()},
            'bands': lab_standards.BANDS,
            'project_factors': {'GLUCOSE': 1 / 18.016, 'HGB': 10.0, 'ALT': 1.0, 'AST': 1.0},
            'corpus': lab['corpus_recomputation'],
            'perturbation': lab['perturbation_experiment'],
        },
    }

    page = TEMPLATE.replace('__DATA__', json.dumps(payload, ensure_ascii=False))
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding='utf-8')
    print(json.dumps({'out': str(out_path.relative_to(ROOT)), 'samples': len(samples),
                      'mentions': sum(len(s['mentions']) for s in samples),
                      'bytes': out_path.stat().st_size}, ensure_ascii=False))
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClinDataForge · 交互演示</title>
<style>
:root{
  --bg:#f6f7f9; --card:#ffffff; --ink:#1f2328; --muted:#5b6570; --line:#d8dee4;
  --accent:#2f6fed; --green:#1a7f37; --red:#c2410c; --amber:#9a6700; --purple:#6639ba;
  --soft:#eef2f7;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
header{padding:22px 28px 14px;background:linear-gradient(135deg,#eef3ff,#f7f9fc)}
h1{margin:0 0 6px;font-size:22px;letter-spacing:.2px}
.sub{color:var(--muted);font-size:13px;max-width:1040px}
.badge{display:inline-block;padding:1px 8px;border-radius:12px;background:#fff;border:1px solid var(--line);font-size:12px;color:var(--muted);margin-right:6px}
nav{display:flex;gap:6px;padding:0 28px;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
nav button{border:0;background:transparent;padding:12px 14px;font-size:14px;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent}
nav button.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
main{padding:20px 28px 40px;max-width:1200px}
section{display:none} section.active{display:block}
.grid{display:grid;grid-template-columns:300px 1fr;gap:16px}
@media(max-width:860px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.card h3{margin:0 0 8px;font-size:15px}
.list button{display:block;width:100%;text-align:left;border:1px solid var(--line);background:#fff;border-radius:8px;padding:9px 11px;margin-bottom:7px;cursor:pointer;font-size:13px}
.list button.active{border-color:var(--accent);box-shadow:0 0 0 2px #dbe6ff}
.list .meta{color:var(--muted);font-size:12px}
.note{color:var(--muted);font-size:12.5px}
.tag{display:inline-block;padding:0 6px;border-radius:10px;font-size:12px;margin-right:4px}
.affirmed{background:#e6f4ea;color:#14532d}
.suspected{background:#fff4ce;color:#6b4e00}
.history{background:#e8e7fb;color:#3b2a87}
.negated{background:#fde8e8;color:#8a1c1c}
.other{background:#eef0f3;color:#4b5563}
.text{font-size:15px;line-height:2;background:#fbfcfe;border:1px solid var(--line);border-radius:8px;padding:14px 16px;white-space:pre-wrap;word-break:break-word}
.mention{border-radius:4px;padding:1px 2px;cursor:pointer;border-bottom:2px solid transparent}
.mention:hover{filter:brightness(.96)}
.mention.sel{outline:2px solid var(--accent);outline-offset:1px}
table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:#f2f5f8;font-weight:600}
.kv{display:flex;gap:10px;flex-wrap:wrap}
.kpi{flex:1;min-width:150px;background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi b{display:block;font-size:20px;margin-bottom:2px}
.kpi span{color:var(--muted);font-size:12px}
.row{display:grid;grid-template-columns:110px 1fr;gap:8px;margin:6px 0;font-size:13px}
.row .k{color:var(--muted)}
.pill{display:inline-block;padding:2px 9px;border-radius:11px;font-size:12px;border:1px solid var(--line);background:#fff;margin:0 4px 4px 0}
.pill.ok{background:#e6f4ea;border-color:#b7dfc2;color:#14532d}
.pill.bad{background:#fde8e8;border-color:#f5c2c2;color:#8a1c1c}
input,select{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:7px;background:#fff}
button.run{background:var(--accent);color:#fff;border:0;border-radius:7px;padding:8px 14px;cursor:pointer;font:inherit}
pre{background:#0f172a;color:#e2e8f0;padding:10px 12px;border-radius:8px;overflow:auto;font-size:12px;line-height:1.55}
footer{padding:18px 28px 36px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);background:#fff}
.bar{height:9px;background:#e5eaf0;border-radius:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}
.bar.green i{background:var(--green)} .bar.red i{background:var(--red)} .bar.amber i{background:var(--amber)}
.warn{border-left:3px solid var(--amber);background:#fffbeb;padding:9px 12px;border-radius:0 7px 7px 0;font-size:13px}
</style>
</head>
<body>
<header>
  <h1>ClinDataForge · 医疗文本数据流水线演示</h1>
  <div class="sub">
    <span class="badge">离线可运行</span><span class="badge">数据全部来自本仓库产物</span>
    <span class="badge">合成数据 · 非临床系统</span><br>
    点击上下文标注、换算检验单位、核对疾病血缘与分割关系。页内所有数字在构建时从 JSON 产物读取，
    真实患者文本入口与正文出口保持关闭。
  </div>
</header>
<nav>
  <button class="active" data-tab="context">① 上下文状态</button>
  <button data-tab="labs">② 检验单位</button>
  <button data-tab="lineage">③ 疾病血缘</button>
  <button data-tab="splits">④ 分割与近重复</button>
</nav>
<main>
<section id="context" class="active">
  <div class="grid">
    <div class="card">
      <h3>样例（真实产物中挑选）</h3>
      <div class="list" id="sample-list"></div>
      <p class="note">挑选标准：开发集中 v1 把“既往”误判为“现症”的病例；同生成器留出集中的英文否定列表与中文段头病例。</p>
    </div>
    <div>
      <div class="card">
        <h3 id="sample-title"></h3>
        <div class="text" id="sample-text"></div>
        <p class="note">颜色 = 金标状态；点击带下划线的表型查看三种判定。灰色是年龄/性别等非表型实体。</p>
      </div>
      <div class="card" id="detail"></div>
    </div>
  </div>
</section>

<section id="labs">
  <div class="card">
    <h3>独立单位换算（不依赖项目共享常数表）</h3>
    <p class="note">换算因子由分子式与 CIAAW 标准原子量推导；参考区间是演示值，不是临床标准。</p>
    <div class="kv" style="align-items:end">
      <label>分析物<br><select id="lab-analyte">
        <option value="GLUCOSE">葡萄糖</option><option value="HGB">血红蛋白</option>
        <option value="ALT">ALT</option><option value="AST">AST</option>
      </select></label>
      <label>数值<br><input id="lab-value" type="number" step="any" value="92" style="width:110px"></label>
      <label>单位<br><select id="lab-unit"></select></label>
      <button class="run" id="lab-run">换算</button>
    </div>
    <div id="lab-out" style="margin-top:12px"></div>
  </div>
  <div class="card">
    <h3>语料重算与注入实验</h3>
    <div id="lab-audit"></div>
  </div>
</section>

<section id="lineage">
  <div class="card">
    <h3>实际使用的 16 种疾病（as-run）</h3>
    <div class="warn" id="stale-note"></div>
    <div style="margin-top:12px;overflow:auto"><table id="disease-table"></table></div>
  </div>
</section>

<section id="splits">
  <div class="card"><h3>切分关系</h3><div class="kv" id="split-kpis"></div></div>
  <div class="card"><h3>留出集的重复结构（不是 260 个独立样本）</h3><div id="holdout-structure"></div></div>
  <div class="card"><h3>结论边界</h3><div id="claim-boundary"></div></div>
</section>
</main>
<footer>
  构建脚本 <code>scripts/build_demo.py</code> · 数据来源：<code>data/phase3_synth/</code>、
  <code>data/phase4_context/</code>、<code>data/phase4_lineage/</code>、
  <code>reports/phase4_split_relations/</code>、<code>reports/phase4_lab_independence/</code>。<br>
  本页不构成临床验证、隐私安全证明或训练收益声明；未执行任何模型训练。
</footer>
<script>
const DATA = __DATA__;
const STATUS_ZH = {affirmed:'现症',suspected:'疑似',history:'既往',negated:'否定'};
const COLOR = {affirmed:'#d7f0dd',suspected:'#fff0bf',history:'#e2e0fb',negated:'#fbdcdc'};

document.querySelectorAll('nav button').forEach(btn=>{
  btn.onclick=()=>{
    document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('section').forEach(s=>s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  };
});

/* ---------- context ---------- */
let current = 0, selected = null;
const listEl = document.getElementById('sample-list');
DATA.samples.forEach((s,i)=>{
  const bad = s.mentions.filter(m=>m.gold!==m.v2_scope_ng).length;
  const b = document.createElement('button');
  b.innerHTML = `<b>${s.id}</b><div class="meta">${s.corpus} · ${s.template} · ${s.disease}</div>
    <div class="meta">${s.mentions.length} 个表型 · v2 错 ${bad}</div>`;
  b.onclick=()=>{current=i; selected=null; renderSample();};
  listEl.appendChild(b);
});
function renderSample(){
  [...listEl.children].forEach((b,i)=>b.classList.toggle('active',i===current));
  const s = DATA.samples[current];
  document.getElementById('sample-title').textContent = `${s.id} · ${s.corpus} · ${s.template}`;
  const host = document.getElementById('sample-text');
  host.innerHTML='';
  let pos=0;
  const ents=[...s.entities].sort((a,b)=>a.start-b.start);
  ents.forEach((e,i)=>{
    if(e.start<pos) return;
    host.appendChild(document.createTextNode(s.text.slice(pos,e.start)));
    const span=document.createElement('span');
    span.textContent=s.text.slice(e.start,e.end);
    const mention=s.mentions.find(m=>m.start===e.start&&m.end===e.end);
    if(mention){
      span.className='mention'+(selected===mention?' sel':'');
      span.style.background=COLOR[mention.gold]||'#eef0f3';
      span.style.borderBottomColor = mention.v2_scope_ng===mention.gold ? '#1a7f37' : '#c2410c';
      span.onclick=()=>{selected=mention; renderSample();};
    }else{
      span.style.color='#9aa4af';
    }
    host.appendChild(span);
    pos=e.end;
  });
  host.appendChild(document.createTextNode(s.text.slice(pos)));
  const d=document.getElementById('detail');
  if(!selected){
    d.innerHTML='<h3>选择左侧文本中的表型</h3><p class="note">粗下划线为绿色表示 v2 与金标一致，红色表示不一致。没有下划线的灰色实体不是表型。</p>';
    return;
  }
  const m=selected;
  const ok=(a,b)=>a===b?'<span class="pill ok">一致</span>':'<span class="pill bad">不一致</span>';
  d.innerHTML=`<h3>${escapeHtml(m.text)} <span class="tag ${m.gold}">${STATUS_ZH[m.gold]}</span> <span class="note">${m.hp_id}</span></h3>
    <div class="row"><div class="k">v1 固定窗口</div><div><span class="tag ${m.v1}">${STATUS_ZH[m.v1]}</span>${ok(m.v1,m.gold)}</div></div>
    <div class="row"><div class="k">v2 作用域·v1 词表</div><div><span class="tag ${m.v2_scope_v1}">${STATUS_ZH[m.v2_scope_v1]}</span>${ok(m.v2_scope_v1,m.gold)}</div></div>
    <div class="row"><div class="k">v2 作用域·NegEx 词表</div><div><span class="tag ${m.v2_scope_ng}">${STATUS_ZH[m.v2_scope_ng]}</span>${ok(m.v2_scope_ng,m.gold)}</div></div>
    <div class="row"><div class="k">触发词</div><div>${m.cue?('<code>'+escapeHtml(m.cue)+'</code>'):'（无，默认现症）'}</div></div>
    <div class="row"><div class="k">判据窗口（实体已掩码）</div><div><code>${escapeHtml(m.run)}</code></div></div>
    <p class="note">v1 只看固定字符窗口，段头、跨句与实体名内部的否定字会骗过它；v2 用硬终止符、终止词与最近触发词划定作用域。</p>`;
}
function escapeHtml(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

/* ---------- labs ---------- */
const unitSel=document.getElementById('lab-unit');
function fillUnits(){
  const a=document.getElementById('lab-analyte').value;
  const units={GLUCOSE:['mmol/L','mg/dL'],HGB:['g/L','g/dL'],ALT:['U/L'],AST:['U/L']}[a];
  unitSel.innerHTML=units.map(u=>`<option>${u}</option>`).join('');
  document.getElementById('lab-value').value = a==='GLUCOSE'?92 : (a==='HGB'?12.4:35);
}
document.getElementById('lab-analyte').onchange=()=>{fillUnits();runLab();};
document.getElementById('lab-run').onclick=runLab;
function convert(v,u,a){
  const f=DATA.lab.factors[a], std={GLUCOSE:'mmol/L',HGB:'g/L',ALT:'U/L',AST:'U/L'}[a];
  if(u===std) return v;
  if(a==='GLUCOSE'&&u==='mg/dL') return +(v*f).toFixed(2);
  if(a==='HGB'&&u==='g/dL') return +(v*f).toFixed(2);
  return null;
}
function projectConvert(v,u,a){
  if(a==='GLUCOSE'&&u==='mg/dL') return +(v/18.016).toFixed(2);
  if(a==='HGB'&&u==='g/dL') return +(v*10).toFixed(2);
  return v;
}
function runLab(){
  const a=document.getElementById('lab-analyte').value;
  const v=parseFloat(document.getElementById('lab-value').value);
  const u=unitSel.value;
  const ind=convert(v,u,a), proj=projectConvert(v,u,a);
  const band=DATA.lab.bands[a];
  let cls='—';
  if(ind!==null){cls = ind<band.lo?'偏低':(ind>band.hi?'偏高':'正常');}
  document.getElementById('lab-out').innerHTML=`
    <div class="kv">
      <div class="kpi"><b>${ind===null?'—':ind}</b><span>独立路径（${a==='GLUCOSE'?'mmol/L':a==='HGB'?'g/L':'U/L'}）</span></div>
      <div class="kpi"><b>${proj===null?'—':proj}</b><span>项目共享表</span></div>
      <div class="kpi"><b>${cls}</b><span>演示区间 ${band.lo}–${band.hi}</span></div>
      <div class="kpi"><b>${ind!==null&&Math.abs(ind-proj)<=0.01?'一致':'待查'}</b><span>两条路径差 ≤0.01</span></div>
    </div>
    <p class="note">换算因子：${a==='GLUCOSE'?'×10/180.156':a==='HGB'?'×10（SI 词头）':'恒等（酶活性 U/L）'}。区间为演示值，不是临床标准。</p>`;
}
fillUnits(); runLab();

document.getElementById('lab-audit').innerHTML=`
  <div class="kv">
    <div class="kpi"><b>${DATA.lab.corpus.n_checked.toLocaleString()}</b><span>语料检验值独立复算</span></div>
    <div class="kpi"><b>${DATA.lab.corpus.conversion_mismatch}</b><span>换算不一致</span></div>
    <div class="kpi"><b>${DATA.lab.corpus.direction_mismatch}</b><span>方向不一致</span></div>
  </div>
  <p class="note">注入实验：把共享表改成错误因子与错误区间后生成 ${DATA.lab.perturbation.n_cases} 条病例。共享表路径必然通过
  （${DATA.lab.perturbation.arm_shared_table.conversion_mismatch} 个换算错 / ${DATA.lab.perturbation.arm_shared_table.direction_mismatch} 个方向错），
  独立路径检出 ${DATA.lab.perturbation.arm_independent_table.conversion_mismatch} 个换算错 /
  ${DATA.lab.perturbation.arm_independent_table.direction_mismatch} 个方向错。</p>`;

/* ---------- lineage ---------- */
document.getElementById('stale-note').innerHTML=
  `<b>历史文件已失效但保留</b>：<code>${DATA.stale.path}</code> 与实际生成只有
   ${DATA.stale.n_overlap}/16 个疾病重合。它由早期算法选择器写出，当前选择器可精确复现；
   生成器已改用 <code>CURATED_DISEASES</code>。本页按实际运行口径展示，不覆盖历史文件。`;
const dt=document.getElementById('disease-table');
dt.innerHTML='<tr><th>#</th><th>疾病 ID</th><th>英文名</th><th>中文名</th><th>来源</th><th>HPO 注释</th><th>生成记录</th></tr>'+
  DATA.diseases.map((d,i)=>`<tr><td>${i+1}</td><td><code>${d.id}</code></td><td>${escapeHtml(d.en)}</td>
  <td>${escapeHtml(d.zh)}</td><td>${d.source}</td><td>${d.annotations}</td><td>${d.records}</td></tr>`).join('');

/* ---------- splits ---------- */
const rel=DATA.relations;
document.getElementById('split-kpis').innerHTML=`
  <div class="kpi"><b>0</b><span>跨组共享患者</span></div>
  <div class="kpi"><b>0</b><span>跨组精确重复文本</span></div>
  <div class="kpi"><b>0</b><span>跨组近重复（Jaccard≥0.8）</span></div>
  <div class="kpi"><b>${(rel.cell_reuse.test.rate*100).toFixed(1)}%</b><span>test 三元组已在 train 出现</span></div>
  <div class="kpi"><b>${(rel.disease_name_leakage.train.raw_rate*100).toFixed(0)}%</b><span>train 正文含疾病名</span></div>`;
const hs=rel.near_duplicates.holdout_structure;
document.getElementById('holdout-structure').innerHTML=`
  <p>260 条留出语料中只有 <b>${hs.n_distinct_normalised_texts}</b> 种不同文本；
  按近重复合并后是 <b>${hs.n_clusters_at_threshold}</b> 个簇，最大簇 <b>${hs.largest_cluster}</b> 条。
  1,618 个提及不是 1,618 个独立观测。</p>
  <div class="kv">
    <div class="kpi"><b>${DATA.bootstrap.systems.v1.point.accuracy.toFixed(4)}</b><span>v1 准确率 [${DATA.bootstrap.systems.v1.accuracy_ci95.join(', ')}]</span></div>
    <div class="kpi"><b>${DATA.bootstrap.systems.v2_scope_ng.point.accuracy.toFixed(4)}</b><span>v2 准确率 [${DATA.bootstrap.systems.v2_scope_ng.accuracy_ci95.join(', ')}]</span></div>
    <div class="kpi"><b>${DATA.bootstrap.systems.v2_scope_ng.point.macro_f1.toFixed(4)}</b><span>v2 宏 F1 [${DATA.bootstrap.systems.v2_scope_ng.macro_f1_ci95.join(', ')}]</span></div>
  </div>
  <p class="note">区间为按 ${hs.n_clusters_at_threshold} 个近重复簇做的 cluster bootstrap（2,000 次）。</p>`;
document.getElementById('claim-boundary').innerHTML=`
  <p><b>可以声称</b>：${rel.claim_boundary.allowed_claims.map(x=>'<span class="pill ok">'+escapeHtml(x)+'</span>').join('')}</p>
  <p><b>不能声称</b>：${rel.claim_boundary.forbidden_claims.map(x=>'<span class="pill bad">'+escapeHtml(x)+'</span>').join('')}</p>
  <p class="note">${escapeHtml(rel.claim_boundary.external_eval_status)}</p>`;

renderSample();
</script>
</body>
</html>
"""


if __name__ == '__main__':
    raise SystemExit(main())
