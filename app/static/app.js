/* Manufacturing Control Tower 前端（无构建步骤，原生 JS + 本地 ECharts）。所有数字均为示例数据。 */
const S = {meta:null, state:{page:'group', month:null, plant:'A', shop:'GA', role:'group'}, charts:[], story:null, storyIdx:0, page:null};
const $ = s => document.querySelector(s);
const PAL = ['#118DFF','#12239E','#E66C37','#6B007B','#E044A7','#744EC2','#D9B300','#D64550','#1AAB40','#15C6F4'];

async function api(path, opt={}){
  opt.headers = Object.assign({'X-CT-Role': S.state.role, 'Content-Type':'application/json'}, opt.headers||{});
  const r = await fetch(path, opt);
  const j = await r.json().catch(()=>({error:'响应解析失败'}));
  if(!r.ok){ throw new Error(j.error || ('HTTP '+r.status)); }
  return j;
}
function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.remove('hidden'); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.add('hidden'),2600); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function closeModal(){ $('#modal').classList.add('hidden'); }
function modal(title, html){ $('#modal-t').textContent=title; $('#modal-b').innerHTML=html; $('#modal').classList.remove('hidden'); }

function readHash(){
  const h = new URLSearchParams(location.hash.slice(1));
  for(const k of ['page','month','plant','shop','role']) if(h.get(k)) S.state[k]=h.get(k);
}
function writeHash(){
  const st=S.state; location.hash = new URLSearchParams({page:st.page, month:st.month, plant:st.plant, shop:st.shop, role:st.role}).toString();
}
function go(nav){
  if(!nav) return;
  Object.assign(S.state, nav);
  if(nav.page && S.meta.shop_pages[nav.page]) S.state.shop = S.meta.shop_pages[nav.page];
  writeHash(); render();
}

async function init(){
  S.meta = await api('/api/meta');
  S.state.month = S.meta.default_month;
  readHash();
  const fill = (sel, items, val) => { sel.innerHTML = items.map(i=>`<option value="${i.id}">${esc(i.name)}</option>`).join(''); sel.value = val; };
  fill($('#sl-month'), S.meta.months.map(m=>({id:m,name:m})), S.state.month);
  fill($('#sl-plant'), S.meta.plants, S.state.plant);
  fill($('#sl-shop'), S.meta.shops, S.state.shop);
  fill($('#sl-role'), S.meta.roles, S.state.role);
  $('#sl-month').onchange = e => go({month:e.target.value});
  $('#sl-plant').onchange = e => go({plant:e.target.value});
  $('#sl-shop').onchange = e => { const sp = Object.entries(S.meta.shop_pages).find(([p,s])=>s===e.target.value); go(sp && S.meta.shop_pages[S.state.page] ? {shop:e.target.value, page:sp[0]} : {shop:e.target.value}); };
  $('#sl-role').onchange = e => { const r = S.meta.roles.find(x=>x.id===e.target.value); const nav={role:r.id}; if(r.plant){nav.plant=r.plant;} if(r.shop){nav.shop=r.shop; nav.page=r.home;} else if(r.plant && S.state.page==='group'){nav.page='plant';} go(nav); toast('已切换角色：'+r.name+'（行级权限已生效）'); };
  $('#btn-story').onclick = startStory;
  $('#story-x').onclick = ()=>{ $('#story').classList.add('hidden'); clearHL(); };
  $('#story-prev').onclick = ()=>storyGo(S.storyIdx-1);
  $('#story-next').onclick = ()=>storyGo(S.storyIdx+1);
  window.addEventListener('resize', ()=>S.charts.forEach(c=>c.resize()));
  window.addEventListener('hashchange', ()=>{ const before=JSON.stringify(S.state); readHash(); if(JSON.stringify(S.state)!==before) render(); });
  render();
}

function renderNav(){
  const role = S.meta.roles.find(r=>r.id===S.state.role) || {};
  const allowed = new Set(role.pages || S.meta.pages.map(p=>p.id));
  let html='', grp=null;
  for(const p of S.meta.pages){
    if(p.group!==grp){ grp=p.group; html+=`<div class="navgrp">${esc(grp)}</div>`; }
    const dis = !allowed.has(p.id);
    const st = (S.page && S.page.nav_status && S.page.nav_status[p.id]) || '';
    html += `<div class="navit ${p.id===S.state.page?'on':''} ${dis?'dis':''}" data-p="${p.id}" title="${dis?'当前角色无权限（行级权限演示）':''}"><span class="dot ${st}"></span>${esc(p.name)}</div>`;
  }
  $('#navlist').innerHTML = html;
  document.querySelectorAll('.navit').forEach(el=>el.onclick=()=>{ if(el.classList.contains('dis')){toast('当前角色无权访问该页面（RLS 演示）');return;} go({page:el.dataset.p}); });
}

async function render(){
  S.charts.forEach(c=>c.dispose()); S.charts=[];
  ['#sl-month','#sl-plant','#sl-shop','#sl-role'].forEach((s,i)=>{ $(s).value = S.state[['month','plant','shop','role'][i]]; });
  const role = S.meta.roles.find(r=>r.id===S.state.role)||{};
  $('#sl-plant').disabled = !!role.plant; $('#sl-shop').disabled = !!role.shop;
  const q = new URLSearchParams({month:S.state.month, plant:S.state.plant, shop:S.state.shop});
  let pg;
  try { pg = await api(`/api/page/${S.state.page}?${q}`); }
  catch(e){ S.page=null; renderNav(); $('#ptitle').textContent='无权限或出错'; $('#psub').textContent=e.message; $('#kpis').innerHTML=''; $('#canvas').innerHTML=`<div class="card" style="grid-column:span 12"><div class="empty">${esc(e.message)}</div></div>`; return; }
  S.page = pg; renderNav();
  $('#ptitle').textContent = pg.title; $('#psub').innerHTML = esc(pg.subtitle||'');
  $('#crumb').innerHTML = (pg.breadcrumb||[]).map((b,i,a)=> i<a.length-1 ? `<a data-i="${i}">${esc(b.label)}</a><span class="sep">›</span>` : `<b>${esc(b.label)}</b>`).join('');
  document.querySelectorAll('#crumb a').forEach(a=>a.onclick=()=>go(pg.breadcrumb[+a.dataset.i].nav));
  $('#pactions').innerHTML = (pg.actions||[]).map((a,i)=>`<button class="btn sm" data-a="${i}">${esc(a.label)}</button>`).join(' ');
  document.querySelectorAll('#pactions button').forEach(b=>b.onclick=()=>pageAction(pg.actions[+b.dataset.a]));
  renderKpis(pg.kpis||[]);
  const cv = $('#canvas'); cv.innerHTML='';
  for(const c of (pg.cards||[])) cv.appendChild(renderCard(c));
  if(S.onRendered){ const f=S.onRendered; S.onRendered=null; setTimeout(f,80); }
}

function renderKpis(kpis){
  const box = $('#kpis'); box.innerHTML=''; box.style.display = kpis.length?'grid':'none';
  for(const k of kpis){
    const d = document.createElement('div');
    d.className = `kpi ${k.status||'na'} ${k.nav?'nav':''}`; d.id = 'kpi-'+k.id;
    const delta = k.delta ? `<b class="${k.status}">${esc(k.delta)}</b> · ` : '';
    d.innerHTML = `<div class="kn" title="${esc(k.name)}">${esc(k.name)}</div><span class="info" title="查看口径">ⓘ</span>
      <div class="kv">${esc(k.value)}<span class="ku">${esc(k.unit||'')}</span></div>
      <div class="kt">${delta}${esc(k.target||'')}</div><div class="spark"></div>`;
    box.appendChild(d);
    if(k.nav) d.onclick = e => { if(!e.target.classList.contains('info')) go(k.nav); };
    d.querySelector('.info').onclick = e => { e.stopPropagation(); showMetric(k.metric_id||k.id); };
    if(k.spark && k.spark.length){
      const ch = echarts.init(d.querySelector('.spark'));
      const col = k.status==='bad'?'#D64550':k.status==='good'?'#1AAB40':'#118DFF';
      ch.setOption({animation:false,grid:{left:0,right:0,top:2,bottom:2},xAxis:{type:'category',show:false,data:k.spark.map((_,i)=>i)},yAxis:{type:'value',show:false,scale:true},
        series:[{type:'line',data:k.spark,symbol:'none',smooth:true,lineStyle:{width:1.5,color:col},areaStyle:{color:col,opacity:.08}}]});
      S.charts.push(ch);
    }
  }
}

function renderCard(c){
  const d = document.createElement('div'); d.className='card'; d.id='card-'+c.id;
  d.style.gridColumn = `span ${c.span||6}`;
  const hint = c.drill ? '<span class="drillhint">可点击穿透 ›</span>' : '';
  d.innerHTML = `<h3>${esc(c.title||'')}${hint}</h3>${c.note?`<div class="cn">${esc(c.note)}</div>`:''}`;
  if(c.kind==='echarts'){
    const el = document.createElement('div'); el.className='chart'; el.style.height=(c.height||260)+'px'; d.appendChild(el);
    setTimeout(()=>{
      const ch = echarts.init(el); const opt = decorate(c.option); ch.setOption(opt); S.charts.push(ch);
      if(c.drill) ch.on('click', p => { const key = c.drill.field==='series' ? p.seriesName : (p.data && p.data.key) || p.name; const nav = c.drill.map ? c.drill.map[key] : null; if(nav) go(nav); });
    },0);
  } else if(c.kind==='table'){
    const w = document.createElement('div'); w.className='tw'; if(c.height) w.style.maxHeight=c.height+'px';
    w.innerHTML = tableHTML(c); d.appendChild(w);
    w.querySelectorAll('[data-nav]').forEach(a=>a.onclick=()=>go(JSON.parse(a.dataset.nav)));
    w.querySelectorAll('[data-metric]').forEach(a=>a.onclick=()=>showMetric(a.dataset.metric));
    w.querySelectorAll('[data-action]').forEach(a=>a.onclick=()=>editAction(+a.dataset.action));
  } else if(c.kind==='html'){
    const w = document.createElement('div'); w.innerHTML = c.html; d.appendChild(w);
  } else if(c.kind==='registry'){
    d.appendChild(registryWidget(c));
  } else if(c.kind==='simulator'){
    d.appendChild(simWidget(c));
  }
  return d;
}

function tableHTML(c){
  const th = c.columns.map(col=>`<th class="${col.num?'num':''}">${esc(col.name)}</th>`).join('');
  const rows = c.rows.map(r=>'<tr>'+r.map((v,i)=>{
    const col=c.columns[i]; const o = (v!==null && typeof v==='object') ? v : {v};
    let inner = esc(o.v);
    if(o.pill) inner = `<span class="pill ${o.pill}">${esc(o.v)}</span>`;
    if(o.nav) inner = `<a data-nav='${esc(JSON.stringify(o.nav))}'>${inner}</a>`;
    if(o.metric) inner = `<a data-metric="${esc(o.metric)}">${inner}</a>`;
    if(o.action) inner = `<a data-action="${o.action}">${inner}</a>`;
    return `<td class="${col.num?'num':''} ${o.cls||''}" title="${esc(o.title||'')}">${inner}</td>`; }).join('')+'</tr>').join('');
  return `<table class="t"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table>`;
}

function decorate(opt){
  opt = JSON.parse(JSON.stringify(opt));
  opt.color = opt.color || PAL;
  opt.textStyle = Object.assign({fontFamily:'"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif'}, opt.textStyle||{});
  if(opt.tooltip===undefined) opt.tooltip = {trigger:'axis'};
  if(!opt.grid && opt.xAxis) opt.grid = {left:48,right:20,top:34,bottom:28,containLabel:true};
  if(opt.legend===undefined && (opt.series||[]).length>1) opt.legend = {top:0,textStyle:{fontSize:11}};
  // 数值格式：series.labelFmt -> label formatter 模板
  return opt;
}

/* ---------- 指标口径库 ---------- */
function registryWidget(c){
  const w = document.createElement('div');
  w.innerHTML = `<input class="search" placeholder="搜索指标名 / 定义 / 公式 / 负责人 / 数据源（例如：加班、VCS、OEE、供应商）">
    <div class="tw" style="max-height:640px"></div>`;
  const draw = q => {
    q = (q||'').trim().toLowerCase();
    const rows = c.rows.filter(r => !q || JSON.stringify(r).toLowerCase().includes(q));
    w.querySelector('.tw').innerHTML = tableHTML({columns:c.columns, rows: rows.map(r=>[{v:r.metric_id},{v:r.name,metric:r.metric_id},r.domain,r.level,r.definition,r.formula,{v:r.target_text},{v:r.warn_text},r.owner_role,r.source,r.refresh])}) + `<div class="cn" style="margin-top:6px">共 ${rows.length} / ${c.rows.length} 项 · 点击指标名查看 SQL 与当前值</div>`;
    w.querySelectorAll('[data-metric]').forEach(a=>a.onclick=()=>showMetric(a.dataset.metric));
  };
  w.querySelector('input').oninput = e => draw(e.target.value);
  draw(''); return w;
}
async function showMetric(id){
  try{
    const m = await api(`/api/metric/${encodeURIComponent(id)}?month=${S.state.month}&plant=${S.state.plant}&shop=${S.state.shop}`);
    const r = m.metric;
    modal(r.name+'（口径）', `<div class="kv2">
      <div>指标编码</div><div>${esc(r.metric_id)}</div><div>业务域 / 层级</div><div>${esc(r.domain)} / ${esc(r.level)}</div>
      <div>业务定义</div><div>${esc(r.definition)}</div><div>计算公式</div><div>${esc(r.formula)}</div>
      <div>目标 / 预警线</div><div>${esc(r.target_text)} / ${esc(r.warn_text)}</div><div>方向</div><div>${r.direction==='up'?'越高越好':r.direction==='down'?'越低越好':'区间'}</div>
      <div>业务负责角色</div><div>${esc(r.owner_role)}</div><div>IT负责角色</div><div>${esc(r.it_role)}</div>
      <div>数据源</div><div>${esc(r.source)}</div><div>刷新频率</div><div>${esc(r.refresh)}</div><div>校验规则</div><div>${esc(r.dq_rule)}</div>
      <div>当前值（${esc(S.state.month)}）</div><div>${(m.values||[]).map(v=>`${esc(v.scope)}：<b>${esc(v.text)}</b>`).join('；')||'—'}</div></div>
      <div style="margin-top:10px;color:#605E5C">ADS 计算 SQL（简化）：</div><pre style="background:#F3F2F1;padding:8px;border-radius:4px;white-space:pre-wrap;font-size:11.5px">${esc(r.sql)}</pre>
      <div class="cn">示例数据 · 指标口径变更须经数据治理小组审批（见技术文档“联邦治理与变更流程”）</div>`);
  }catch(e){ toast(e.message); }
}

/* ---------- 异常→行动 ---------- */
async function editAction(id){
  const a = (S.page.action_index||{})[id]; if(!a) return;
  const opts = S.meta.action_status.map(s=>`<option ${s===a.status?'selected':''}>${s}</option>`).join('');
  modal('行动项 #'+id, `<div class="kv2"><div>异常</div><div>${esc(a.title)}</div><div>指标</div><div>${esc(a.metric_name)}（${esc(a.scope)}）</div>
     <div>实际 / 预警线</div><div>${esc(a.actual_text)} / ${esc(a.warn_text)}</div><div>责任角色</div><div>${esc(a.owner_role)}</div><div>到期日</div><div>${esc(a.due_date)}</div>
     <div>创建 / 关闭</div><div>${esc(a.created_at)} / ${esc(a.closed_at||'—')}</div></div>
     <div class="form-row" style="margin-top:10px">状态 <select id="ac-st">${opts}</select></div>
     <div class="form-row">备注 <input id="ac-note" style="flex:1" value="${esc(a.note||'')}" placeholder="根因 / 对策 / 验证结果"></div>
     <div class="form-row"><button class="btn primary" id="ac-save">保存</button><span class="cn">状态改为“已关闭”时自动记录关闭时间，用于统计关闭周期</span></div>`);
  $('#ac-save').onclick = async ()=>{
    try{ await api(`/api/actions/${id}`, {method:'POST', body:JSON.stringify({status:$('#ac-st').value, note:$('#ac-note').value})}); closeModal(); toast('已更新行动项 #'+id); render(); }
    catch(e){ toast(e.message); }
  };
}
async function pageAction(a){
  try{ const r = await api(a.endpoint, {method:'POST', body:JSON.stringify(Object.assign({month:S.state.month}, a.body||{}))}); toast(r.message||'完成'); render(); }
  catch(e){ toast(e.message); }
}

/* ---------- VCS 情景模拟 ---------- */
function simWidget(c){
  const w = document.createElement('div');
  w.innerHTML = `<div class="slider-row">
     <label>需求变化 <input type="range" id="sim-vol" min="-30" max="30" step="5" value="0"> <b id="sim-vol-v">0%</b></label>
     <label>工资变化 <input type="range" id="sim-wage" min="-5" max="10" step="1" value="0"> <b id="sim-wage-v">0%</b></label>
     <label>电价变化 <input type="range" id="sim-elec" min="-20" max="30" step="5" value="0"> <b id="sim-elec-v">0%</b></label>
     <label>策略 <select id="sim-strat"><option value="cost">成本优先</option><option value="stable">稳定优先（班次不随月波动）</option></select></label></div>
     <div class="chart" id="sim-chart" style="height:${c.height||300}px"></div><div id="sim-tbl"></div>`;
  const run = async ()=>{
    const p = {vol:+w.querySelector('#sim-vol').value, wage:+w.querySelector('#sim-wage').value, elec:+w.querySelector('#sim-elec').value, strategy:w.querySelector('#sim-strat').value};
    ['vol','wage','elec'].forEach(k=>w.querySelector(`#sim-${k}-v`).textContent=(p[k]>0?'+':'')+p[k]+'%');
    try{
      const r = await api(`/api/vcs/simulate?month=${S.state.month}&plant=${S.state.plant}&vol=${p.vol}&wage=${p.wage}&elec=${p.elec}&strategy=${p.strategy}`);
      let ch = echarts.getInstanceByDom(w.querySelector('#sim-chart')); if(!ch){ ch = echarts.init(w.querySelector('#sim-chart')); S.charts.push(ch); }
      ch.setOption(decorate(r.option), true);
      w.querySelector('#sim-tbl').innerHTML = tableHTML(r.table);
    }catch(e){ toast(e.message); }
  };
  w.querySelectorAll('input,select').forEach(el=>el.oninput=run);
  setTimeout(run, 50); return w;
}

/* ---------- 演示故事 ---------- */
async function startStory(){
  try{ S.story = await api('/api/story?month='+S.state.month); }catch(e){ toast(e.message); return; }
  if(S.state.role!=='group'){ S.state.role='group'; toast('演示故事使用“集团”角色'); }
  $('#story').classList.remove('hidden'); storyGo(0);
}
function clearHL(){ document.querySelectorAll('.hl').forEach(e=>e.classList.remove('hl')); }
function storyGo(i){
  const st = S.story.steps; if(i<0||i>=st.length){ if(i>=st.length){ $('#story').classList.add('hidden'); clearHL(); toast('演示结束'); } return; }
  S.storyIdx=i; const s=st[i];
  $('#story-step').textContent = `演示故事 · 第 ${i+1} / ${st.length} 步`;
  $('#story-title').textContent = s.title; $('#story-text').innerHTML = s.text;
  $('#story-next').textContent = i===st.length-1 ? '结束' : '下一步';
  S.onRendered = ()=>{ clearHL(); (s.highlight||[]).forEach(h=>{ const el=document.getElementById(h); if(el){ el.classList.add('hl'); el.scrollIntoView({behavior:'smooth',block:'center'}); } }); };
  go(Object.assign({role:'group'}, s.nav));
}

init().catch(e=>{ document.body.innerHTML = '<div style="padding:40px">启动失败：'+esc(e.message)+'</div>'; });
