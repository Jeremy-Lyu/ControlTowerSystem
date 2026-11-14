"""页面与指标 API。生产形态对应 Power BI + ADS；本演示用查询模拟。全部为示例数据。"""
from __future__ import annotations
import json, datetime as dt, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etl.common import (PLANTS, PLANT_NAME, SHOPS, SHOP_NAME, SHOP_CODE, MONTHS, STORY_MONTH,
                        load_story, SLOT_NAME)

class Forbidden(Exception): pass
class BadRequest(Exception): pass

PAGES = [
    dict(id='group', name='集团总览', group='经营总览'),
    dict(id='plant', name='工厂视图', group='经营总览'),
    dict(id='vcs', name='VCS联动', group='经营总览'),
    dict(id='cost', name='成本', group='经营总览'),
    dict(id='plan', name='计划交付', group='经营总览'),
    dict(id='stamping', name='冲压', group='车间'),
    dict(id='body', name='焊装', group='车间'),
    dict(id='paint', name='涂装', group='车间'),
    dict(id='assembly', name='总装', group='车间'),
    dict(id='quality', name='质量', group='职能'),
    dict(id='logistics', name='物流', group='职能'),
    dict(id='energy', name='能源', group='职能'),
    dict(id='workforce', name='人力', group='职能'),
    dict(id='maint', name='设备维护', group='职能'),
    dict(id='safety', name='安全环境', group='职能'),
    dict(id='governance', name='数据治理', group='治理与闭环'),
    dict(id='registry', name='指标口径库', group='治理与闭环'),
    dict(id='actions', name='异常行动', group='治理与闭环'),
    dict(id='rootcause', name='根因关系', group='治理与闭环'),
    dict(id='benchmark', name='工厂对标', group='治理与闭环'),
]
SHOP_PAGES = {'stamping':'ST','body':'BD','paint':'PT','assembly':'GA'}
ROLES = [
    dict(id='group', name='集团（全部）', pages=[p['id'] for p in PAGES], plant=None, shop=None, home='group'),
    dict(id='plant_A', name='A工厂厂长', pages=[p['id'] for p in PAGES if p['id']!='group'], plant='A', shop=None, home='plant'),
    dict(id='plant_B', name='B工厂厂长', pages=[p['id'] for p in PAGES if p['id'] not in ('group','assembly') or True], plant='B', shop=None, home='plant'),
    dict(id='ga_A', name='A工厂总装车间主任', pages=['assembly','quality','logistics','workforce','vcs','actions','registry','rootcause','plan'], plant='A', shop='GA', home='assembly'),
    dict(id='logistics_A', name='A工厂物流经理', pages=['logistics','assembly','plan','actions','registry','rootcause','plant'], plant='A', shop=None, home='logistics'),
]
# B厂长不能看集团页
ROLES[2]['pages'] = [p['id'] for p in PAGES if p['id']!='group']

def _allowed(role):
    r = next((x for x in ROLES if x['id']==role), ROLES[0])
    return r

def _check(role, page, plant, shop):
    r = _allowed(role)
    if page not in r['pages']:
        raise Forbidden('当前角色无权访问该页面（行级权限演示）')
    if r['plant'] and plant != r['plant']:
        raise Forbidden('当前角色只能查看本工厂数据（行级权限演示）')
    if r['shop'] and page in SHOP_PAGES and SHOP_PAGES[page] != r['shop']:
        raise Forbidden('当前角色只能查看本车间数据（行级权限演示）')
    return r

def route(con, method, path, q, body, role):
    if path == '/api/meta' and method=='GET':
        return 200, meta(con)
    if path.startswith('/api/page/') and method=='GET':
        page = path.split('/')[-1]
        month = q.get('month') or STORY_MONTH
        plant = q.get('plant') or 'A'
        shop = q.get('shop') or 'GA'
        _check(role, page, plant, shop)
        fn = PAGE_FN.get(page)
        if not fn: raise BadRequest('未知页面：'+page)
        return 200, fn(con, month, plant, shop, role)
    if path.startswith('/api/metric/') and method=='GET':
        mid = path.split('/')[-1]
        return 200, metric_detail(con, mid, q.get('month') or STORY_MONTH, q.get('plant') or 'A', q.get('shop'))
    if path.startswith('/api/actions/') and method=='POST':
        aid = int(path.split('/')[-1])
        return 200, update_action(con, aid, body)
    if path == '/api/actions/refresh' and method=='POST':
        return 200, {'message':'预警已按当前月份重新扫描（演示环境行动项保持示例）','ok':True}
    if path == '/api/story' and method=='GET':
        return 200, demo_story(con, q.get('month') or STORY_MONTH)
    if path == '/api/vcs/simulate' and method=='GET':
        return 200, vcs_simulate(con, q)
    if path == '/api/health' and method=='GET':
        n = con.execute('SELECT COUNT(*) n FROM ads_kpi_value').fetchone()['n']
        return 200, {'ok':True, 'metrics_rows':n, 'label':'EXAMPLE-DATA'}
    raise BadRequest('未知接口')

def meta(con):
    S = load_story()
    return dict(
        default_month=STORY_MONTH, months=MONTHS,
        plants=[{'id':p,'name':PLANT_NAME[p]} for p in PLANTS],
        shops=[{'id':s,'name':SHOP_NAME[s]} for s in SHOPS],
        roles=ROLES, pages=PAGES, shop_pages=SHOP_PAGES,
        action_status=['开放','处理中','待验证','已关闭'],
        data_label='示例数据', group_name='X集团',
        vcs_src=S.get('VCS_SRC','VCS v5.2 示例数据'),
    )

def kpi(con, mid, month, plant=None, shop=None, nav=None):
    if shop:
        r = con.execute("SELECT * FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code=?",
                        (mid, month, plant, shop)).fetchone()
    elif plant:
        r = con.execute("SELECT * FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code IS NULL",
                        (mid, month, plant)).fetchone()
    else:
        r = con.execute("SELECT * FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code IS NULL",
                        (mid, month)).fetchone()
    if not r:
        # fallback plant if group missing
        return None
    m = con.execute("SELECT name, unit, target_text FROM dim_metric WHERE metric_id=?", (mid,)).fetchone()
    spark = [x['value'] for x in con.execute(
        "SELECT value FROM ads_kpi_spark WHERE metric_id=? AND (plant_code IS ? OR (plant_code IS NULL AND ? IS NULL)) AND (shop_code IS ? OR (shop_code IS NULL AND ? IS NULL)) ORDER BY month",
        (mid, plant, plant, shop, shop))]
    tgt = r['target']
    tgt_txt = (m['target_text'] if m else '') or ''
    if tgt is not None and r['unit'] in ('元/台','kWh/台','h/台','万元','%'):
        if r['unit']=='元/台': tgt_s = f"VCS ¥{int(tgt):,}"
        elif r['unit']=='%': tgt_s = f"目标 {tgt:g}%" if 'VCS' not in tgt_txt else f"VCS {tgt:g}%"
        else: tgt_s = f"VCS {tgt:g} {r['unit']}"
        if 'VCS' in tgt_txt or mid in ('unit_cost','elec_kwh','hpv','ot_rate','en_cost','lab_cost','cost_total','paint_kwh'):
            tgt_s = f"VCS {tgt:g}{r['unit']}" if r['unit']!='元/台' else f"VCS ¥{int(tgt):,}"
    else:
        tgt_s = tgt_txt
    return dict(id=mid, metric_id=mid, name=m['name'] if m else mid, value=r['text'].replace('¥','').replace('万',''),
                raw=r['value'], unit=r['unit'] if r['unit'] not in r['text'] else '',
                target=tgt_s or tgt_txt, delta=_delta(r, m), status=r['status'] or 'na',
                spark=spark, nav=nav)

def _delta(r, m):
    if r['metric_id'] in ('backtest','backlog','headcount','jph_shift','wcs_buffer','pbs_buffer','ready'): return ''
    if r['target'] is None or r['value'] is None: return ''
    if r['unit']=='%':
        return f"{r['value']-r['target']:+.1f} pp"
    if r['metric_id'] in ('unit_cost','lab_cost','en_cost','cost_total','elec_kwh','hpv','paint_kwh'):
        if r['target']:
            pct = (r['value']-r['target'])/r['target']*100
            return f"{pct:+.1f}%"
    return ''

def kpis(con, ids, month, plant=None, shop=None):
    out=[]
    for item in ids:
        if isinstance(item, tuple):
            mid, nav = item[0], item[1]
        else:
            mid, nav = item, None
        c = kpi(con, mid, month, plant, shop, nav)
        if c: out.append(c)
    return out

def nav_status(con, month, plant):
    st={}
    mapping={'group':'unit_cost','plant':'ot_rate','vcs':'vcs_exec','cost':'unit_cost','plan':'ach_rate',
             'stamping':'oee','body':'oee','paint':'paint_kwh','assembly':'ga_stop','quality':'dpu',
             'logistics':'lg_ontime','energy':'elec_kwh','workforce':'ot_rate','maint':'pm_rate',
             'safety':'ltir','governance':'dq_pass','actions':'vcs_exec'}
    for page, mid in mapping.items():
        if page=='group':
            r=con.execute("SELECT status FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code IS NULL",(mid,month)).fetchone()
        elif page in SHOP_PAGES:
            r=con.execute("SELECT status FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code=?",
                          ('oee' if mid=='oee' else mid, month, plant, SHOP_PAGES[page])).fetchone()
            if page=='assembly':
                r=con.execute("SELECT status FROM ads_kpi_value WHERE metric_id='ga_stop' AND month=? AND plant_code=? AND shop_code='GA'",(month,plant)).fetchone()
            if page=='paint':
                r=con.execute("SELECT status FROM ads_kpi_value WHERE metric_id='paint_kwh' AND month=? AND plant_code=? AND shop_code='PT'",(month,plant)).fetchone()
        else:
            r=con.execute("SELECT status FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code IS NULL",(mid,month,plant)).fetchone()
        st[page]= r['status'] if r else 'na'
    return st

def crumb(*items):
    return list(items)

def echart(cid, title, option, span=6, height=260, note='', drill=None):
    return dict(id=cid, kind='echarts', title=title, option=option, span=span, height=height, note=note, drill=drill)

def table(cid, title, columns, rows, span=6, height=None, note=''):
    return dict(id=cid, kind='table', title=title, columns=columns, rows=rows, span=span, height=height, note=note)

def html(cid, title, content, span=12):
    return dict(id=cid, kind='html', title=title, html=content, span=span)

def insight(text, span=12, cid='insight'):
    return html(cid, '', f'<div class="insight">{text}</div>', span)

# -------------------- pages --------------------
def page_group(con, month, plant, shop, role):
    S=load_story()
    cards=[]
    # trend
    months, act, tgt = [], [], []
    for r in con.execute("SELECT month, cost_total*1.0/prod_qty v, cost_plan_total*1.0/plan_qty t FROM dws_group_month ORDER BY month"):
        months.append(r['month']); act.append(round(r['v'])); tgt.append(round(r['t']))
    cards.append(echart('trend','集团单车转换成本 12 个月趋势 vs VCS 测算','',span=6))
    cards[-1]['option']=dict(
        xAxis=dict(type='category', data=months),
        yAxis=dict(type='value', name='元/台', min=int(min(act+tgt)-80)),
        series=[
            dict(name='实际', type='line', data=act, smooth=True, lineStyle=dict(width=2.4)),
            dict(name='VCS 测算', type='line', data=tgt, smooth=True, lineStyle=dict(type='dashed', width=1.6, color='#D64550')),
        ])
    # plant bar
    names, vals, tgts, mapd = [], [], [], {}
    for r in con.execute("SELECT plant_code, cost_total*1.0/prod_qty v, cost_plan_total*1.0/plan_qty t FROM dws_plant_month WHERE month=? ORDER BY plant_code",(month,)):
        names.append(PLANT_NAME[r['plant_code']]); vals.append(round(r['v'])); tgts.append(round(r['t']))
        mapd[PLANT_NAME[r['plant_code']]]=dict(page='plant', plant=r['plant_code'])
    cards.append(echart('pbar','各工厂单车转换成本 vs VCS 测算','',span=6, drill=dict(field='name', map=mapd), note='点击柱体进入工厂视图'))
    cards[-1]['option']=dict(
        tooltip=dict(trigger='axis'),
        xAxis=dict(type='category', data=names), yAxis=dict(type='value', name='元/台'),
        series=[dict(name='实际', type='bar', data=[{'value':v,'itemStyle':{'color':'#D64550' if v>t else '#1AAB40'},'key':n} for v,t,n in zip(vals,tgts,names)], label=dict(show=True)),
                dict(name='VCS 测算', type='line', data=tgts, symbol='none', lineStyle=dict(type='dashed', color='#201F1E'))])
    # mix
    mix=list(con.execute("""SELECT grp, SUM(amount) a FROM dws_cost_account_month WHERE month=? GROUP BY grp""",(month,)))
    tot=sum(r['a'] for r in mix) or 1
    cards.append(echart('mix','集团转换成本构成（VCS 科目归并）','',span=4, height=240))
    cards[-1]['option']=dict(tooltip=dict(trigger='item'), series=[dict(type='pie', radius=['45%','70%'],
        data=[dict(name=r['grp'].split('（')[0], value=round(r['a']/tot*100)) for r in mix])])
    # matrix
    rows=[]
    targets=['VCS 测算','≥98%','≥95%','VCS 测算','VCS 测算','≥85%']
    mids_mat=[('unit_cost',None),('ach_rate',None),('otd',None),('elec_kwh',None),('ot_rate','plant'),('oee','plant')]
    header=['工厂']+[con.execute("SELECT name FROM dim_metric WHERE metric_id=?",(m,)).fetchone()['name'] for m,_ in mids_mat]
    cols=[{'name':h,'num':i>0} for i,h in enumerate(header)]
    def cell(mid, p):
        if p is None:
            r=con.execute("SELECT text,status FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code IS NULL",(mid,month)).fetchone()
        else:
            r=con.execute("SELECT text,status FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code IS NULL",(mid,month,p)).fetchone()
        if not r: return {'v':'—','cls':''}
        return {'v':r['text'],'cls':'bg-'+r['status'],'nav':dict(page='plant',plant=p) if p else None}
    for p,n in ([('A','A工厂'),('B','B工厂'),('C','C工厂'),(None,'集团合计')]):
        row=[{'v':n,'nav':dict(page='plant',plant=p) if p else dict(page='group')}]
        for mid, need in mids_mat:
            if need=='plant' and p is None: row.append({'v':'—'}); continue
            row.append(cell(mid,p))
        rows.append(row)
    cards.append(table('matrix','工厂指标矩阵（条件格式，示例数据）', cols, rows, span=8, note='绿=达标 / 黄=预警 / 红=超标。点击工厂名进入工厂视图。'))
    # top alerts
    alerts=list(con.execute("""SELECT title, owner_role, actual_text, action_id, metric_id FROM ads_action
                               WHERE month=? AND status!='已关闭' ORDER BY action_id LIMIT 5""",(month,)))
    cards.append(table('alerts','Top 异常（自动预警 → 行动项）',
                       [{'name':'异常'},{'name':'实际'},{'name':'责任角色'},{'name':'行动'}],
                       [[{'v':a['title'],'nav':dict(page='actions')}, a['actual_text'] or '', a['owner_role'],
                         {'v':'查看','action':a['action_id']}] for a in alerts], span=12))
    cards.insert(0, insight(f'示例数据声明：X集团 / A·B·C 工厂，{month}。集团单车转换成本 ¥5,202，高于 VCS 测算 ¥4,980（+4.5%），主要由 <b>A工厂 ¥5,512 vs ¥4,997（+10.3%）</b> 拉动。产量达成率 96.9%（25,340 / 26,150）。点击 A工厂可沿「加班 → 总装缺件 → 供应商 S07 → VCS 执行率」下钻。'))
    return _pack('集团总览', f'X集团 · {month} · 全部为示例数据 · 目标 = VCS 当月测算',
                 crumb(dict(label='集团总览', nav=dict(page='group'))),
                 kpis(con, [('unit_cost', dict(page='cost')), ('ach_rate', dict(page='plan')),
                            ('otd', dict(page='plan')), ('elec_kwh', dict(page='energy'))], month),
                 cards, month, plant, actions=[], nav=nav_status(con,month,plant))

def page_plant(con, month, plant, shop, role):
    pn=PLANT_NAME[plant]
    k = kpis(con, ['jph','oee','ot_rate','shift_util','buffer_days','vcs_exec'], month, plant)
    cards=[insight(f'{pn} · {month}（示例）。单车转换成本见「成本 / VCS联动」页。工厂 JPH 取总装下线口径。故事线：加班率高于 VCS 测算，根因在总装缺件与方案执行偏离。' if plant=='A' else f'{pn} · {month}（示例）。')]
    # weekly oee/jph — use daily aggregated to week for story weeks if A oct else monthly N/A
    weeks, oee, jph = _week_series(con, month, plant)
    if weeks:
        cards.append(echart('wj','周度 OEE / JPH达成率', '', span=6))
        cards[-1]['option']=dict(xAxis=dict(type='category',data=weeks), yAxis=dict(type='value',min=70,max=100),
            series=[dict(name='JPH达成率',type='line',data=jph), dict(name='OEE',type='line',data=oee)])
    shops, oees, jphs, mapd = [], [], [], {}
    for s in SHOPS:
        r=con.execute("SELECT oee,jph_rate FROM dws_shop_month WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        shops.append(SHOP_NAME[s]); oees.append(r['oee'] if r else None); jphs.append(r['jph_rate'] if r else None)
        mapd[SHOP_NAME[s]]=dict(page={'ST':'stamping','BD':'body','PT':'paint','GA':'assembly'}[s], plant=plant, shop=s)
    cards.append(echart('sh','四大车间 OEE vs JPH达成率','',span=6, drill=dict(field='name',map=mapd), note='点击车间进入对应车间页'))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=shops), yAxis=dict(type='value',min=60,max=100),
        series=[dict(name='OEE',type='bar',data=[{'value':v,'key':n} for v,n in zip(oees,shops)]),
                dict(name='JPH达成率',type='bar',data=[{'value':v,'key':n} for v,n in zip(jphs,shops)])])
    # function strip
    fn=kpis(con,['ftt','dpu','lg_ontime','lineside_lt4','elec_kwh','idle_share','attend','hpv'], month, plant)
    cards.append(table('fn','质量 / 物流 / 能源 / 人力 摘要',
                       [{'name':'指标'},{'name':'实际'},{'name':'状态'}],
                       [[{'v':x['name'],'metric':x['metric_id']}, x['value']+(x['unit'] or ''), {'v':{'bad':'超标','warn':'预警','good':'达标'}.get(x['status'],x['status']),'pill':x['status']}] for x in fn],
                       span=6))
    # OT by shop
    names, ots, rates=[],[],[]
    for s in SHOPS:
        r=con.execute("SELECT ot_h, std_h FROM dws_shop_month WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        names.append(SHOP_NAME[s]); ots.append(int(r['ot_h']) if r else 0); rates.append(round(r['ot_h']*100/r['std_h'],1) if r else 0)
    cards.append(echart('ot','各车间加班人·h 与加班率','',span=6))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=names), yAxis=[dict(type='value',name='人·h'),dict(type='value',name='%')],
        series=[dict(name='加班人·h',type='bar',data=ots), dict(name='加班率',type='line',yAxisIndex=1,data=rates)])
    # VCS plan vs act
    rows=[]
    for s in SHOPS:
        r=con.execute("SELECT * FROM dws_shop_month WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        ev=con.execute("SELECT text,status FROM ads_kpi_value WHERE metric_id='vcs_exec' AND month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        r4 = r['ot_line_h_act']/r['shifts']
        r4s = '违规' if r4>60 else ('溢价' if r4>36 else '合规')
        rows.append([{'v':SHOP_NAME[s],'nav':dict(page={'ST':'stamping','BD':'body','PT':'paint','GA':'assembly'}[s],plant=plant,shop=s)},
                     f"{r['tier_plan']}×{r['shifts']}", f"{r['tier_act']}×{r['shifts']}",
                     {'v':round(r['ot_line_h_plan'],1),'num':True}, {'v':round(r['ot_line_h_act'],1),'num':True},
                     {'v':ev['text'] if ev else '','cls':'bg-'+(ev['status'] if ev else '')},
                     {'v':f'{r4:.1f} h','cls':'bg-bad' if r4>36 else 'bg-good'}, r4s])
    cards.append(table('vcs','VCS 推荐方案 vs 实际（JPH档×班次、线体加班、执行率、R4 人均加班）',
                       [{'name':'车间'},{'name':'推荐 JPH×班'},{'name':'实际 JPH×班'},{'name':'建议加班 h','num':True},
                        {'name':'实际加班 h','num':True},{'name':'执行率'},{'name':'人均加班'},{'name':'R4'}],
                       rows, span=12, note='执行率 = 一致车间天数 ÷ 工作日。R4：36 h 常规上限，60 h 绝对上限（示例参数）。'))
    return _pack(f'工厂视图 · {pn}', f'{month} · 示例数据 · 目标 = VCS 当月测算',
                 crumb(dict(label='集团', nav=dict(page='group')), dict(label=pn, nav=dict(page='plant',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def _week_series(con, month, plant):
    rows=list(con.execute("""SELECT d.week_label, MIN(p.biz_date) first_d, SUM(p.run_min) run_min, SUM(p.planned_min) planned_min,
                                    SUM(CASE WHEN p.shop_code='GA' THEN p.output_qty ELSE 0 END) out_ga
                             FROM dwd_fact_production p JOIN dim_date d ON d.d=p.biz_date
                             WHERE p.plant_code=? AND p.biz_date<=(SELECT MAX(d) FROM dim_date WHERE month=?)
                             GROUP BY d.week_label ORDER BY first_d""",(plant,month)))
    rows=rows[-13:]
    # also oee approx run/planned * jph?
    shops=list(con.execute("""SELECT d.week_label, p.shop_code, SUM(run_min) run_min, SUM(planned_min) planned_min, AVG(design_jph) design, SUM(output_qty) out
                              FROM dwd_fact_production p JOIN dim_date d ON d.d=p.biz_date
                              WHERE p.plant_code=? AND p.biz_date<=(SELECT MAX(d) FROM dim_date WHERE month=?) GROUP BY 1,2""",(plant,month)))
    from collections import defaultdict
    by=defaultdict(list)
    for r in shops:
        oee=(r['run_min']/r['planned_min'])*(r['out']/(r['design']*r['run_min']/60) if r['design'] and r['run_min'] else 0)*100
        by[r['week_label']].append(oee)
    weeks, oee, jph=[],[],[]
    for r in rows:
        weeks.append(r['week_label'])
        oee.append(round(sum(by[r['week_label']])/max(1,len(by[r['week_label']])),1))
    for r in rows:
        ga=con.execute("""SELECT SUM(output_qty) o, SUM(run_min) rm, MAX(tier_jph) t FROM dwd_fact_production p JOIN dim_date d ON d.d=p.biz_date
                          WHERE p.plant_code=? AND p.shop_code='GA' AND d.week_label=? AND p.biz_date<=(SELECT MAX(d) FROM dim_date WHERE month=?)""",(plant,r['week_label'],month)).fetchone()
        jph.append(round(ga['o']/(ga['rm']/60)/ga['t']*100,1) if ga and ga['rm'] and ga['t'] else None)
    return weeks, oee, jph

def page_shop(shop_code, title_zh):
    def fn(con, month, plant, shop, role):
        shop=shop_code
        pn=PLANT_NAME[plant]
        r=con.execute("SELECT * FROM dws_shop_month WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,shop)).fetchone()
        badge=f"VCS 推荐 {r['tier_plan']}×{r['shifts']} 班 · 实际 {r['tier_act']}×{r['shifts']} · 线体加班 {r['ot_line_h_act']:.1f} h（建议 {r['ot_line_h_plan']:.1f}）· 人均 {r['ot_line_h_act']/r['shifts']:.1f} h · 执行率 {round(r['exec_days']*100/r['workdays'])}%"
        mid_map={'ST':['smed','die_util','spm','st_q','oee','ot_rate'],
                 'BD':['robot_down','takt','body_ftt','oee','ot_rate'],
                 'PT':['paint_kwh','paint_ftt','oven_idle','oven_comp','oee','ot_rate'],
                 'GA':['ga_stop','short_cnt','rework','andon','takt']}
        k=kpis(con, mid_map[shop], month, plant, shop)
        cards=[html('vcsbadge','VCS 方案（示例）', f'<div class="insight"><b>{badge}</b> · 可选档 { "30/40/50" if shop=="ST" else "24/30/36" }</div>', 12)]
        # downtime pareto
        rows=list(con.execute("SELECT reason, SUM(minutes) m FROM dwd_fact_downtime WHERE month=? AND plant_code=? AND shop_code=? GROUP BY reason ORDER BY m DESC",(month,plant,shop)))
        if rows:
            cards.append(echart('pareto','停线/停机原因 Pareto','',span=6))
            cards[-1]['option']=dict(xAxis=dict(type='category',data=[x['reason'] for x in rows], axisLabel=dict(rotate=20)),
                yAxis=dict(type='value',name='分钟'), series=[dict(type='bar',data=[x['m'] for x in rows], itemStyle=dict(color='#118DFF'))])
        if shop=='ST':
            lines=list(con.execute("""SELECT line_code, SUM(die_run_min)*100.0/SUM(die_avail_min) die,
                                             SUM(actual_strokes)*100.0/SUM(design_strokes) spm,
                                             SUM(good_parts)*100.0/SUM(parts) q, AVG(0) x
                                      FROM dwd_fact_press WHERE month=? AND plant_code=? GROUP BY line_code ORDER BY line_code""",(month,plant)))
            smeds=list(con.execute("SELECT line_code, AVG(minutes) a, COUNT(*) n FROM dwd_fact_die_change WHERE month=? AND plant_code=? GROUP BY 1",(month,plant)))
            smap={x['line_code']:x['a'] for x in smeds}
            cards.append(table('lines','压机线明细（示例）',
                [{'name':'线'},{'name':'换模分钟/次','num':True},{'name':'模具稼动率','num':True},{'name':'冲次达成','num':True},{'name':'合格率','num':True}],
                [[{'v':x['line_code']}, {'v':f"{smap.get(x['line_code'],0):.1f}",'cls':'bg-bad' if smap.get(x['line_code'],0)>10 else 'bg-good'},
                  {'v':f"{x['die']:.1f}%",'cls':'bg-bad' if x['die']<85 else 'bg-good'},
                  {'v':f"{x['spm']:.1f}%",'cls':'bg-bad' if x['spm']<90 else 'bg-good'},
                  {'v':f"{x['q']:.1f}%",'cls':'bg-bad' if x['q']<99 else 'bg-good'}] for x in lines], span=6))
        if shop=='BD':
            top=list(con.execute("""SELECT equip_code, SUM(minutes) m FROM dwd_fact_downtime
                                    WHERE month=? AND plant_code=? AND reason='机器人故障' GROUP BY 1 ORDER BY m DESC LIMIT 10""",(month,plant)))
            cards.append(echart('rb','机器人停机 Top 10 工位','',span=6,height=300))
            cards[-1]['option']=dict(yAxis=dict(type='category',data=[x['equip_code'].split('-BD-')[-1] for x in reversed(top)]),
                xAxis=dict(type='value',name='分钟'), series=[dict(type='bar',data=[x['m'] for x in reversed(top)])])
        if shop=='PT':
            ov=list(con.execute("""SELECT oven_code, SUM(idle_min)*1.0/SUM(shifts) idle, SUM(compliant)*100.0/SUM(start_stop) comp
                                   FROM dwd_fact_oven WHERE month=? AND plant_code=? GROUP BY 1 ORDER BY oven_code""",(month,plant)))
            names=[x['oven_code'] for x in ov]
            cards.append(echart('ov','各烘房 空烘时长 vs 开停合规率','',span=6))
            cards[-1]['option']=dict(xAxis=dict(type='category',data=names,axisLabel=dict(rotate=15)),
                yAxis=[dict(type='value',name='分钟/班'),dict(type='value',name='%')],
                series=[dict(name='空烘',type='bar',data=[round(x['idle'],1) for x in ov]),
                        dict(name='合规率',type='line',yAxisIndex=1,data=[round(x['comp']) for x in ov])])
            days=list(con.execute("""SELECT e.biz_date, SUM(e.elec_kwh)/NULLIF((SELECT SUM(output_qty) FROM dwd_fact_production p WHERE p.biz_date=e.biz_date AND p.plant_code=e.plant_code AND p.shop_code='GA'),0) u
                                     FROM dwd_fact_energy e WHERE e.month=? AND e.plant_code=? AND e.shop_code='PT' GROUP BY e.biz_date ORDER BY 1""",(month,plant)))
            cards.append(echart('pe','每日涂装单车电耗（示例）','',span=6))
            cards[-1]['option']=dict(xAxis=dict(type='category',data=[x['biz_date'][8:] for x in days]), yAxis=dict(type='value'),
                series=[dict(type='line',data=[round(x['u'],1) if x['u'] else None for x in days])])
        if shop=='GA':
            parts=list(con.execute("""SELECT d.part_no, p.part_name, d.supplier_code, COUNT(*) c, SUM(d.minutes) m,
                                             (SELECT SUM(ontime_batches)*100.0/SUM(batches) FROM dwd_fact_delivery x
                                              WHERE x.month=d.month AND x.plant_code=d.plant_code AND x.supplier_code=d.supplier_code) rate,
                                             (SELECT buffer_h FROM dwd_fact_lineside l WHERE l.month=d.month AND l.plant_code=d.plant_code AND l.part_no=d.part_no)
                                      FROM dwd_fact_downtime d LEFT JOIN dim_part p ON p.part_no=d.part_no
                                      WHERE d.month=? AND d.plant_code=? AND d.shop_code='GA' AND d.reason='缺件' AND d.part_no IS NOT NULL
                                      GROUP BY 1,2,3 ORDER BY m DESC LIMIT 10""",(month,plant)))
            cards.append(table('parts','缺件零件 Top 10（示例）',
                [{'name':'零件号'},{'name':'名称'},{'name':'供应商'},{'name':'次数','num':True},{'name':'分钟','num':True},{'name':'到货准时率','num':True},{'name':'线边缓冲 h','num':True}],
                [[{'v':x['part_no']}, x['part_name'] or '', {'v':x['supplier_code'],'nav':dict(page='logistics',plant=plant)},
                  x['c'], x['m'], {'v':f"{x['rate']:.1f}%" if x['rate'] else '—','cls':'bg-bad' if x['rate'] and x['rate']<90 else ''},
                  {'v':x[6] if x[6] is not None else '—','cls':'bg-bad' if (x[6] or 99)<2 else ''}] for x in parts], span=12,
                note='点击供应商进入物流页。故事首位：P-30117 / S07。'))
            # daily stop stacked
            days=list(con.execute("SELECT biz_date, short_min, other_min FROM dws_ga_daily WHERE month=? AND plant_code=? ORDER BY 1",(month,plant)))
            cards.append(echart('ds','每日停线时长（缺件 vs 其他）','',span=6))
            cards[-1]['option']=dict(xAxis=dict(type='category',data=[x['biz_date'][8:] for x in days]), yAxis=dict(type='value',name='分钟'),
                series=[dict(name='缺件',type='bar',stack='s',data=[x['short_min'] for x in days],itemStyle=dict(color='#D64550')),
                        dict(name='其他',type='bar',stack='s',data=[x['other_min'] for x in days])])
        return _pack(f'{title_zh} · {pn}', f'{month} · 示例数据 · {badge}',
                     crumb(dict(label='集团',nav=dict(page='group')), dict(label=pn,nav=dict(page='plant',plant=plant)),
                           dict(label=title_zh, nav=dict(page={'ST':'stamping','BD':'body','PT':'paint','GA':'assembly'}[shop],plant=plant,shop=shop))),
                     k, cards, month, plant, nav=nav_status(con,month,plant))
    return fn

def page_quality(con, month, plant, shop, role):
    k=kpis(con,['ftt','dpu','audit','warranty','rework'], month, plant)
    # rework is shop GA
    k=kpis(con,['ftt','dpu','audit','warranty'], month, plant)+kpis(con,['rework'], month, plant, 'GA')
    defs=list(con.execute("""SELECT m.defect_group, m.shop_code, SUM(d.qty) q FROM dwd_fact_defect d
                             JOIN dim_defect m ON m.defect_code=d.defect_code
                             WHERE d.month=? AND d.plant_code=? GROUP BY 1,2 ORDER BY q DESC LIMIT 12""",(month,plant)))
    cards=[echart('pareto','Top 缺陷 Pareto（按车间着色，示例）','',span=7)]
    color={'ST':'#118DFF','BD':'#744EC2','PT':'#E66C37','GA':'#D64550'}
    cards[-1]['option']=dict(xAxis=dict(type='category',data=[x['defect_group'] for x in defs],axisLabel=dict(rotate=25)),
        yAxis=dict(type='value'), series=[dict(type='bar', data=[{'value':x['q'],'itemStyle':{'color':color.get(x['shop_code'],'#118DFF')}} for x in defs])])
    ftt=list(con.execute("SELECT shop_code, ftt_rate FROM dws_shop_month WHERE month=? AND plant_code=?",(month,plant)))
    # ST ftt from press
    st=con.execute("SELECT text FROM ads_kpi_value WHERE metric_id='st_q' AND month=? AND plant_code=?",(month,plant)).fetchone()
    names, vals=[],[]
    tgt={'ST':99,'BD':95,'PT':90,'GA':95}
    for s in SHOPS:
        names.append(SHOP_NAME[s])
        if s=='ST' and st: vals.append(float(st['text'].replace('%','')))
        else:
            row=next((x for x in ftt if x['shop_code']==s), None)
            vals.append(round(row['ftt_rate'],1) if row and row['ftt_rate'] else None)
    cards.append(echart('ftt','各车间一次合格率 vs 目标','',span=5))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=names), yAxis=dict(type='value',min=85,max=100),
        series=[dict(name='实际',type='bar',data=vals), dict(name='目标',type='scatter',data=[tgt[s] for s in SHOPS])])
    dpu_t=[]
    for m in MONTHS:
        r=con.execute("SELECT defect_qty*1.0/prod_qty v FROM dws_plant_month WHERE month=? AND plant_code=?",(m,plant)).fetchone()
        dpu_t.append(round(r['v'],2) if r else None)
    cards.append(echart('dput','DPU 12 个月趋势','',span=6))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=MONTHS), yAxis=dict(type='value'),
        series=[dict(name='DPU',type='line',data=dpu_t), dict(name='目标 0.50',type='line',data=[0.50]*12,lineStyle=dict(type='dashed',color='#D64550'))])
    return _pack(f'质量 · {PLANT_NAME[plant]}', f'{month} · 示例数据',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='质量',nav=dict(page='quality',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_logistics(con, month, plant, shop, role):
    k=kpis(con,['lg_ontime','buffer_days','lineside_lt4','otd'], month, plant)
    k += kpis(con,['short_cnt'], month, plant, 'GA')
    sup=list(con.execute("""SELECT supplier_code, SUM(ontime_batches)*100.0/SUM(batches) r, SUM(batches) b
                            FROM dwd_fact_delivery WHERE month=? AND plant_code=? GROUP BY 1 ORDER BY r""",(month,plant)))
    cards=[echart('sup','供应商到货准时率排名（示例）','',span=6,height=320)]
    cards[-1]['option']=dict(yAxis=dict(type='category',data=[x['supplier_code'] for x in reversed(sup)]),
        xAxis=dict(type='value',max=100,name='%'),
        series=[dict(type='bar', data=[{'value':round(x['r'],1),'itemStyle':{'color':'#D64550' if x['r']<90 else ('#E8A33D' if x['r']<95 else '#1AAB40')}} for x in reversed(sup)])])
    # shortage contribution
    contr=list(con.execute("""SELECT supplier_code, COUNT(*) c, SUM(minutes) m FROM dwd_fact_downtime
                              WHERE month=? AND plant_code=? AND reason='缺件' AND supplier_code IS NOT NULL
                              GROUP BY 1 ORDER BY m DESC LIMIT 8""",(month,plant)))
    if contr:
        cards.append(echart('sc','供应商缺件贡献（次数 / 分钟，示例）','',span=6))
        cards[-1]['option']=dict(xAxis=dict(type='category',data=[x['supplier_code'] for x in contr]),
            yAxis=[dict(type='value',name='分钟'),dict(type='value',name='次')],
            series=[dict(name='分钟',type='bar',data=[x['m'] for x in contr]), dict(name='次数',type='line',yAxisIndex=1,data=[x['c'] for x in contr])])
    buckets=[('<1h',0,1),('1–2h',1,2),('2–4h',2,4),('4–8h',4,8),('>8h',8,100)]
    bdata=[]
    for name,lo,hi in buckets:
        n=con.execute("SELECT COUNT(*) n FROM dwd_fact_lineside WHERE month=? AND plant_code=? AND buffer_h>=? AND buffer_h<?",(month,plant,lo,hi)).fetchone()['n']
        bdata.append((name,n))
    cards.append(echart('lb','关键零件线边缓冲分布（示例）','',span=6))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=[x[0] for x in bdata]), yAxis=dict(type='value',name='零件数'),
        series=[dict(type='bar',data=[{'value':n,'itemStyle':{'color':'#D64550' if i<3 else '#118DFF'}} for i,(_,n) in enumerate(bdata)])])
    return _pack(f'物流 · {PLANT_NAME[plant]}', f'{month} · 示例数据 · 缓冲库存天数指外购件，车身缓存见 VCS联动',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='物流',nav=dict(page='logistics',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_energy(con, month, plant, shop, role):
    k=kpis(con,['elec_kwh','idle_share','peak_share','en_cost'], month, plant)+kpis(con,['paint_kwh'], month, plant, 'PT')
    shops, series = [], {k:[] for k in ('fix','ot','var')}
    for s in SHOPS:
        r=con.execute("SELECT SUM(fix_kwh) f, SUM(ot_kwh) o, SUM(var_kwh) v FROM dwd_fact_energy WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        prod=con.execute("SELECT prod_qty FROM dws_plant_month WHERE month=? AND plant_code=?",(month,plant)).fetchone()['prod_qty']
        shops.append(SHOP_NAME[s])
        series['fix'].append(round(r['f']/prod,1)); series['ot'].append(round(r['o']/prod,1)); series['var'].append(round(r['v']/prod,1))
    cards=[echart('st','各车间单车电耗（固定 / 加班 / 变动，VCS 口径）','',span=7, note='分母为工厂下线车数。VCS 只计电，不含天然气等。')]
    cards[-1]['option']=dict(xAxis=dict(type='category',data=shops), yAxis=dict(type='value',name='kWh/台'),
        series=[dict(name=n,type='bar',stack='e',data=series[k]) for n,k in [('固定（功率×开动）','fix'),('加班','ot'),('变动（单车）','var')]])
    idle=list(con.execute("SELECT shop_code, SUM(idle_kwh)*100.0/SUM(elec_kwh) v FROM dwd_fact_energy WHERE month=? AND plant_code=? GROUP BY 1",(month,plant)))
    cards.append(echart('id','空载/待机能耗占比（按车间）','',span=5))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=[SHOP_NAME[x['shop_code']] for x in idle]), yAxis=dict(type='value',name='%'),
        series=[dict(type='bar',data=[{'value':round(x['v'],1),'itemStyle':{'color':'#D64550' if x['v']>10 else '#1AAB40'}} for x in idle])])
    tr, tg=[],[]
    for m in MONTHS:
        r=con.execute("SELECT energy_cost/prod_qty a, energy_cost_plan/plan_qty t FROM dws_plant_month WHERE month=? AND plant_code=?",(m,plant)).fetchone()
        tr.append(round(r['a']) if r else None); tg.append(round(r['t']) if r else None)
    cards.append(echart('ct','能源成本 12 个月 vs VCS 测算','',span=6))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=MONTHS), yAxis=dict(type='value',name='元/台'),
        series=[dict(name='实际',type='line',data=tr), dict(name='VCS 测算',type='line',data=tg,lineStyle=dict(type='dashed',color='#D64550'))])
    return _pack(f'能源 · {PLANT_NAME[plant]}', f'{month} · 示例数据 · 电价分时（峰 1.10 / 平 0.70 / 谷 0.35，加权约 0.75 元/kWh）',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='能源',nav=dict(page='energy',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_workforce(con, month, plant, shop, role):
    k=kpis(con,['headcount','attend','hpv','ot_rate','temp_share','lab_cost','disp_share'], month, plant)
    cards=[]
    # roster
    rows=[]
    for s in SHOPS:
        rec={x['emp_type']:x['headcount'] for x in con.execute("SELECT emp_type,headcount FROM dwd_fact_roster WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,s))}
        tot=sum(rec.values()); tmp=rec.get('派遣',0)+rec.get('临时',0)
        rows.append([SHOP_NAME[s], rec.get('正式',0), rec.get('派遣',0), rec.get('临时',0), tot,
                     {'v':f'{tmp/tot*100:.1f}%' if tot else '—','cls':'bg-bad' if tot and tmp/tot>0.2 else ''}])
    cards.append(table('ro','各车间在册人员结构（正式 / 派遣 / 临时，示例）',
                       [{'name':'车间'},{'name':'正式','num':True},{'name':'派遣','num':True},{'name':'临时','num':True},{'name':'合计','num':True},{'name':'派遣+临时'}], rows, span=6,
                       note='在册 = VCS 定员（直接+间接）×班次。外包按班次计费，不计入人数。'))
    names, ots, rates=[],[],[]
    for s in SHOPS:
        r=con.execute("SELECT ot_h,std_h,ot_line_h_act,shifts FROM dws_shop_month WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        names.append(SHOP_NAME[s]); ots.append(int(r['ot_h'])); rates.append(round(r['ot_line_h_act']/r['shifts'],1))
    cards.append(echart('r4','人均月加班 vs R4 上限（36 / 60 h，示例）','',span=6))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=names), yAxis=dict(type='value',name='h'),
        series=[dict(name='人均加班',type='bar',data=rates),
                dict(name='36h 常规',type='line',data=[36]*4,lineStyle=dict(type='dashed',color='#E8A33D')),
                dict(name='60h 绝对',type='line',data=[60]*4,lineStyle=dict(type='dashed',color='#D64550'))])
    tr,tg=[],[]
    for m in MONTHS:
        r=con.execute("""SELECT SUM(c.amount)/p.prod_qty a, SUM(c.plan_amount)/p.plan_qty t
                         FROM dws_cost_account_month c JOIN dws_plant_month p ON p.month=c.month AND p.plant_code=c.plant_code
                         WHERE c.month=? AND c.plant_code=? AND c.grp IN ('人工（含间接/夜班/福利）','加班（含超限溢价）') GROUP BY p.prod_qty,p.plan_qty""",(m,plant)).fetchone()
        tr.append(round(r['a']) if r else None); tg.append(round(r['t']) if r else None)
    cards.append(echart('lc','人工成本（含加班）vs VCS 测算','',span=12,height=220))
    cards[-1]['option']=dict(xAxis=dict(type='category',data=MONTHS), yAxis=dict(type='value',name='元/台'),
        series=[dict(name='实际',type='line',data=tr), dict(name='VCS 测算',type='line',data=tg,lineStyle=dict(type='dashed',color='#D64550'))])
    return _pack(f'人力 · {PLANT_NAME[plant]}', f'{month} · 示例数据',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='人力',nav=dict(page='workforce',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_vcs(con, month, plant, shop, role):
    S=load_story()
    k=kpis(con,['cost_total','unit_cost','backlog','backtest','ot_premium','budget_limit'], month, plant if plant else 'A')
    # waterfall
    accs=list(con.execute("""SELECT account, grp, amount, plan_amount FROM dws_cost_account_month
                             WHERE month=? AND plant_code=? ORDER BY (SELECT seq FROM dim_account d WHERE d.account=dws_cost_account_month.account)""",(month,plant)))
    # group by grp
    from collections import OrderedDict
    g=OrderedDict()
    for r in accs:
        key=r['grp']
        g.setdefault(key, [0,0]); g[key][0]+=r['plan_amount']; g[key][1]+=r['amount']
    names=['VCS 测算']+ [k.split('（')[0] for k in g]+['实际合计']
    # waterfall data: start, then diffs, then total
    plan=sum(v[0] for v in g.values())/1e4
    act=sum(v[1] for v in g.values())/1e4
    diffs=[(v[1]-v[0])/1e4 for v in g.values()]
    wf=[round(plan,1)]+ [round(d,1) for d in diffs]+[round(act,1)]
    cards=[echart('wf',f'{PLANT_NAME[plant]} 转换成本瀑布：VCS 测算 → 实际（万元，示例）','',span=8,height=300,
                  note=f'总额 {act:,.1f} 万 vs 测算 {plan:,.1f} 万（{(act-plan)/plan*100:+.1f}%）。单车偏差可分解为产量摊薄与花费偏差（见 UNIT_BRIDGE）。')]
    # simple bar of plan vs act by group
    cards[-1]['option']=dict(tooltip=dict(trigger='axis'),
        xAxis=dict(type='category',data=[k.split('（')[0] for k in g],axisLabel=dict(rotate=20)),
        yAxis=dict(type='value',name='万元'),
        series=[dict(name='VCS 测算',type='bar',data=[round(v[0]/1e4,1) for v in g.values()]),
                dict(name='实际',type='bar',data=[round(v[1]/1e4,1) for v in g.values()])])
    # unit bridge
    if plant=='A' and month==STORY_MONTH:
        ub=S['UNIT_BRIDGE']
        cards.append(html('br','单车成本桥梁（示例）',
            f"<div class='insight'>计划单车 <b>¥{ub[0]:,}</b> → 产量摊薄 <b>+{ub[1]}</b> 元/台 → 花费偏差 <b>+{ub[2]}</b> 元/台 → 实际 <b>¥{ub[3]:,}</b>。"
            f"回测：成本总额 +3.7%（在 ±5% 内），产量 −6.0%（超 ±2%）。“成本没超阈值”不等于“测算准确”。</div>", 4))
    # jph x shift table
    rows=[]
    for s in SHOPS:
        r=con.execute("SELECT * FROM dws_shop_month WHERE month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        ev=con.execute("SELECT text FROM ads_kpi_value WHERE metric_id='vcs_exec' AND month=? AND plant_code=? AND shop_code=?",(month,plant,s)).fetchone()
        r4=r['ot_line_h_act']/r['shifts']
        rows.append([SHOP_NAME[s], f"{r['tier_plan']}×{r['shifts']}", f"{r['tier_act']}×{r['shifts']}",
                     round(r['ot_line_h_plan'],1), round(r['ot_line_h_act'],1), ev['text'] if ev else '',
                     f"{r4:.1f}", '违规' if r4>60 else ('溢价' if r4>36 else '合规')])
    cards.append(table('js','各车间 JPH档 × 班次 推荐 vs 实际（含 R4 判定、执行率）',
                       [{'name':'车间'},{'name':'推荐'},{'name':'实际'},{'name':'建议加班 h','num':True},{'name':'实际加班 h','num':True},
                        {'name':'执行率'},{'name':'人均加班 h'},{'name':'R4'}], rows, span=7))
    # buffers
    bufs=list(con.execute("""SELECT p.buffer_code, b.buffer_name, p.cap_units, p.cap_effective, p.plan_end,
                                    (SELECT level_units FROM dwd_fact_buffer f WHERE f.plant_code=p.plant_code AND f.month=p.month AND f.buffer_code=p.buffer_code
                                     ORDER BY f.biz_date DESC LIMIT 1) act
                             FROM dwd_fact_vcs_buffer_plan p JOIN dim_buffer b ON b.buffer_code=p.buffer_code
                             WHERE p.month=? AND p.plant_code=? AND p.scenario_id='VCS-BASE'""",(month,plant)))
    cards.append(table('bf','车间间缓存 vs 有效上限（R1，示例）',
                       [{'name':'缓存'},{'name':'台数上限','num':True},{'name':'有效上限','num':True},{'name':'VCS 计划月末','num':True},{'name':'实际月末','num':True},{'name':'状态'}],
                       [[x['buffer_name'], x['cap_units'], x['cap_effective'], x['plan_end'], x['act'],
                         {'v':'已满' if x['act']>=x['cap_effective'] else '正常','pill':'bad' if x['act']>=x['cap_effective'] else 'closed'}] for x in bufs],
                       span=5, note='有效上限 = 台数上限与载具上限取小。PBS 示例 500/500 已满。'))
    # sensitivity
    scen=list(con.execute("SELECT scenario_name, value FROM dwd_vcs_scenario WHERE scenario_type='敏感性' AND metric='单车转换成本'"))
    if scen:
        cards.append(echart('sen','年度基准包敏感性（单车成本，示例）','',span=6, note='口径为年度基准包（约 3,619 元/台），与本月 FULL_COST 4,997 元/台不同，见评审 C1。'))
        cards[-1]['option']=dict(xAxis=dict(type='category',data=[x['scenario_name'] for x in scen],axisLabel=dict(rotate=15)),
            yAxis=dict(type='value',name='元/台'), series=[dict(type='bar',data=[x['value'] for x in scen])])
    lim=list(con.execute("SELECT scenario_name, value, unit FROM dwd_vcs_scenario WHERE scenario_type='预算安全边界'"))
    strat=list(con.execute("SELECT scenario_name, value, note FROM dwd_vcs_scenario WHERE scenario_type='策略溢价'"))
    cards.append(table('lim','预算安全边界与策略溢价（示例，年度包）',
                       [{'name':'项目'},{'name':'值'},{'name':'说明'}],
                       [[x['scenario_name'], f"{x['value']}{x['unit']}", '不突破“基准+3%”预算前'] for x in lim]
                       + [[x['scenario_name'], f"{x['value']}%", x['note'] or '相对成本优先'] for x in strat]
                       + [['超预算概率（稳健方案）','5%','成本优先 25%、稳定0.5 为 70%（示例）']],
                       span=6))
    cards.append(dict(id='sim', kind='simulator', title='情景模拟（基于年度包弹性的示意，非求解器）', span=12, height=280,
                      note='演示用线性/查表近似，不调用 VCS 求解器。'))
    cards.insert(0, insight('VCS联动把控制塔的“看得见”与产量成本测算的“算得准”接起来：看板提供实际，VCS 给推荐方案与目标，偏差按科目/车间回写校准。A工厂示例：方案 冲压 40×2、焊装/涂装/总装 36×2；总成本 5,699.8 万 vs 测算 5,497.0 万。'))
    return _pack(f'VCS联动 · {PLANT_NAME[plant]}', f'{month} · 示例数据 · 场景 VCS-BASE / v5.2 · 目标 = VCS 测算',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='VCS联动',nav=dict(page='vcs',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_cost(con, month, plant, shop, role):
    k=kpis(con,['unit_cost','cost_total','budget_exec','lab_cost','en_cost','copq'], month, plant)
    accs=list(con.execute("SELECT account, grp, amount, plan_amount FROM dws_cost_account_month WHERE month=? AND plant_code=? ORDER BY grp, account",(month,plant)))
    rows=[[x['grp'].split('（')[0], x['account'], {'v':f"{x['plan_amount']/1e4:,.1f}",'num':True},
           {'v':f"{x['amount']/1e4:,.1f}",'num':True}, {'v':f"{(x['amount']-x['plan_amount'])/1e4:,.1f}",'cls':'bg-bad' if x['amount']>x['plan_amount']*1.05 else ''}] for x in accs]
    cards=[table('acc','VCS 17 个转换成本科目（万元，示例）',
                 [{'name':'分组'},{'name':'科目'},{'name':'VCS 测算','num':True},{'name':'实际','num':True},{'name':'偏差','num':True}], rows, span=12)]
    return _pack(f'成本 · {PLANT_NAME[plant]}', f'{month} · 示例数据 · 不含材料',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='成本',nav=dict(page='cost',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_plan(con, month, plant, shop, role):
    k=kpis(con,['ach_rate','otd','plan_stab','lead_time','wip_days','fg_days','buffer_days','backlog'], month, plant)
    days=list(con.execute("""SELECT p.biz_date, p.plan_qty, a.output_qty FROM dwd_fact_plan_daily p
                             LEFT JOIN dws_ga_daily a ON a.biz_date=p.biz_date AND a.plant_code=p.plant_code
                             WHERE p.month=? AND p.plant_code=? ORDER BY 1""",(month,plant)))
    cards=[echart('pd','日计划 vs 总装下线（冻结版，示例）','',span=8)]
    cards[-1]['option']=dict(xAxis=dict(type='category',data=[x['biz_date'][8:] for x in days]), yAxis=dict(type='value'),
        series=[dict(name='冻结计划',type='line',data=[x['plan_qty'] for x in days]), dict(name='实际下线',type='bar',data=[x['output_qty'] for x in days])])
    chg=list(con.execute("SELECT change_date, shop_code, reason, in_frozen FROM dwd_fact_plan_change WHERE month=? AND plant_code=? ORDER BY change_date",(month,plant)))
    cards.append(table('cg','冻结期内计划变更（示例）',
                       [{'name':'日期'},{'name':'车间'},{'name':'原因'},{'name':'冻结期内'}],
                       [[x['change_date'], SHOP_NAME.get(x['shop_code'],x['shop_code']), x['reason'], '是' if x['in_frozen'] else '否'] for x in chg[:20]],
                       span=4, height=280))
    return _pack(f'计划交付 · {PLANT_NAME[plant]}', f'{month} · 示例数据',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='计划交付',nav=dict(page='plan',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_maint(con, month, plant, shop, role):
    k=kpis(con,['mtbf','mttr','pm_rate','equip_avail','spare_stock'], month, plant)
    top=list(con.execute("""SELECT e.equip_name, e.shop_code, COUNT(*) n, SUM(d.minutes) m
                            FROM dwd_fact_downtime d JOIN dim_equipment e ON e.equip_code=d.equip_code
                            WHERE d.month=? AND d.plant_code=? AND d.reason IN ('设备故障','机器人故障','模具故障','输送链故障','喷涂机器人','烘房温控','夹具','输送','焊枪/电极')
                            GROUP BY 1,2 ORDER BY m DESC LIMIT 10""",(month,plant)))
    cards=[table('top','关键设备故障 Top 10（示例）',
                 [{'name':'设备'},{'name':'车间'},{'name':'次数','num':True},{'name':'分钟','num':True}],
                 [[x['equip_name'], SHOP_NAME.get(x['shop_code'],''), x['n'], x['m']] for x in top], span=12)]
    return _pack(f'设备维护 · {PLANT_NAME[plant]}', f'{month} · 示例数据',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='设备维护',nav=dict(page='maint',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_safety(con, month, plant, shop, role):
    k=kpis(con,['ltir','hazard_close','co2_unit','water_unit'], month, plant)
    inc=list(con.execute("SELECT inc_type, COUNT(*) n, SUM(lost_days) d FROM dwd_fact_incident WHERE month=? AND plant_code=? GROUP BY 1",(month,plant)))
    cards=[table('inc','事故/事件（示例）', [{'name':'类型'},{'name':'件数','num':True},{'name':'损失工日','num':True}],
                 [[x['inc_type'],x['n'],x['d']] for x in inc], span=6),
           insight('碳排放按电力 0.57 kgCO2/kWh 的示例因子估算，仅用于演示 ESG 指标形态，不是官方盘查。', 6)]
    return _pack(f'安全环境 · {PLANT_NAME[plant]}', f'{month} · 示例数据',
                 crumb(dict(label='集团',nav=dict(page='group')), dict(label=PLANT_NAME[plant],nav=dict(page='plant',plant=plant)), dict(label='安全环境',nav=dict(page='safety',plant=plant))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_gov(con, month, plant, shop, role):
    k=kpis(con,['job_ontime','dq_pass','mau','metric_views'], month)
    rules=list(con.execute("SELECT rule_id,name,layer,severity,checked,failed,note FROM dwd_dq_result ORDER BY rule_id"))
    cards=[table('dq','本轮 ETL 数据质量规则结果（示例）',
                 [{'name':'规则'},{'name':'名称'},{'name':'层'},{'name':'级别'},{'name':'检查','num':True},{'name':'未通过','num':True},{'name':'说明'}],
                 [[x['rule_id'],x['name'],x['layer'],x['severity'],x['checked'],{'v':x['failed'],'cls':'bg-warn' if x['failed'] else 'bg-good'},x['note']] for x in rules], span=12)]
    return _pack('数据治理', f'{month} · 示例数据 · 联邦治理：集团定口径，工厂管数据，IT 管平台',
                 crumb(dict(label='数据治理',nav=dict(page='governance'))),
                 k, cards, month, plant, nav=nav_status(con,month,plant))

def page_registry(con, month, plant, shop, role):
    rows=list(con.execute("SELECT * FROM dim_metric ORDER BY metric_id"))
    data=dict(id='reg', kind='registry', title='指标口径库（可搜索）', span=12,
              columns=[{'name':'编码'},{'name':'指标名'},{'name':'业务域'},{'name':'层级'},{'name':'定义'},{'name':'公式'},
                       {'name':'目标'},{'name':'预警'},{'name':'业务负责角色'},{'name':'数据源'},{'name':'刷新'}],
              rows=[dict(metric_id=r['metric_id'], name=r['name'], domain=r['domain'], level=r['level'],
                         definition=r['definition'], formula=r['formula'], target_text=r['target_text'],
                         warn_text=r['warn_text'], owner_role=r['owner_role'], source=r['source'], refresh=r['refresh']) for r in rows])
    return _pack('指标口径库', f'共 {len(rows)} 项 · 示例数据 · 变更须经数据治理小组审批',
                 crumb(dict(label='指标口径库',nav=dict(page='registry'))),
                 [], [data], month, plant, nav=nav_status(con,month,plant))

def page_actions(con, month, plant, shop, role):
    rows=list(con.execute("SELECT * FROM ads_action WHERE month=? ORDER BY action_id",(month,)))
    idx={r['action_id']:dict(r) for r in rows}
    tab=table('ac','异常 → 行动闭环（示例，可更新状态）',
              [{'name':'#'},{'name':'异常'},{'name':'范围'},{'name':'实际'},{'name':'责任角色'},{'name':'状态'},{'name':'到期'},{'name':'关闭时间'}],
              [[{'v':r['action_id'],'action':r['action_id']}, {'v':r['title'],'action':r['action_id']},
                (PLANT_NAME.get(r['plant_code'],'')+(SHOP_NAME.get(r['shop_code'],'') if r['shop_code'] else '')),
                r['actual_text'] or '', r['owner_role'], {'v':r['status'],'pill':{'开放':'open','处理中':'doing','待验证':'verify','已关闭':'closed'}.get(r['status'],'')},
                r['due_date'], r['closed_at'] or '—'] for r in rows], span=12,
              note='点击标题可改状态；关闭时自动记录关闭时间。')
    return _pack('异常行动', f'{month} · 由预警线自动生成的示例待办，状态可在演示中更新（写入本地 SQLite）',
                 crumb(dict(label='异常行动',nav=dict(page='actions'))),
                 [], [tab], month, plant, nav=nav_status(con,month,plant),
                 extra={'action_index': idx},
                 actions=[dict(label='按预警重新扫描', endpoint='/api/actions/refresh')])

def page_root(con, month, plant, shop, role):
    nodes=[dict(id=r['node_id'], kind=r['kind'], label=r['label'], sub=r['sub'], value=r['value'], status=r['status'])
           for r in con.execute('SELECT * FROM ads_graph_node')]
    edges=[dict(source=r['src'], target=r['dst'], rel=r['rel'], label=r['label'], weight=r['weight'])
           for r in con.execute('SELECT * FROM ads_graph_edge')]
    # echarts graph
    cats=['metric','event','shop','part','supplier']
    data=[{'id':n['id'],'name':n['label'],'category':cats.index(n['kind']) if n['kind'] in cats else 0,
           'value':n['value'] or 0, 'tooltip':{'formatter':n['label']+'<br>'+(n['sub'] or '')}} for n in nodes]
    links=[{'source':e['source'],'target':e['target'],'label':{'show':True,'formatter':e['rel']}} for e in edges]
    cards=[echart('g','根因关系图：停线 → 缺件 → 零件 → 供应商（Ontology 风格，示例）','',span=8,height=420,
                  note='A工厂 2026-10 故事：缺件占停线 54%，首位 P-30117 / S07。')]
    cards[-1]['option']=dict(tooltip=dict(trigger='item'),
        legend=dict(data=['指标','事件','车间','零件','供应商']),
        series=[dict(type='graph', layout='force', roam=True, label=dict(show=True, fontSize=11),
                     categories=[{'name':n} for n in ['指标','事件','车间','零件','供应商']],
                     data=data, links=links, force=dict(repulsion=280, edgeLength=90))])
    cards.append(table('e','关系说明', [{'name':'从'},{'name':'到'},{'name':'关系'},{'name':'说明'}],
                       [[e['source'], e['target'], e['rel'], e['label']] for e in edges], span=4, height=420))
    return _pack('根因关系', f'{month} · {PLANT_NAME[plant]} · 示例数据',
                 crumb(dict(label='根因关系',nav=dict(page='rootcause',plant=plant))),
                 [], cards, month, plant, nav=nav_status(con,month,plant))

def page_bench(con, month, plant, shop, role):
    mids=['unit_cost','ach_rate','oee','ot_rate','elec_kwh','hpv','vcs_exec','lg_ontime','ftt','dpu']
    header=['指标']+[PLANT_NAME[p] for p in PLANTS]
    rows=[]
    for mid in mids:
        name=con.execute("SELECT name FROM dim_metric WHERE metric_id=?",(mid,)).fetchone()['name']
        row=[{'v':name,'metric':mid}]
        for p in PLANTS:
            r=con.execute("SELECT text,status FROM ads_kpi_value WHERE metric_id=? AND month=? AND plant_code=? AND shop_code IS NULL",(mid,month,p)).fetchone()
            row.append({'v':r['text'] if r else '—','cls':'bg-'+(r['status'] if r else 'na'),'nav':dict(page='plant',plant=p)})
        rows.append(row)
    cards=[table('b',f'{month} 三工厂对标（示例）', [{'name':h,'num':i>0} for i,h in enumerate(header)], rows, span=12,
                 note='同一口径、同一目标（VCS 测算或固定阈值）。可用于全球推广时复制最佳实践。')]
    return _pack('工厂对标', f'{month} · 示例数据',
                 crumb(dict(label='工厂对标',nav=dict(page='benchmark'))),
                 [], cards, month, plant, nav=nav_status(con,month,plant))

def _pack(title, sub, breadcrumb, kpis_, cards, month, plant, actions=None, nav=None, extra=None):
    out=dict(title=title, subtitle=sub, breadcrumb=breadcrumb, kpis=kpis_ or [], cards=cards or [],
             actions=actions or [], nav_status=nav or {}, data_label='示例数据')
    if extra: out.update(extra)
    return out

def metric_detail(con, mid, month, plant, shop):
    m=con.execute("SELECT * FROM dim_metric WHERE metric_id=?", (mid,)).fetchone()
    if not m: raise BadRequest('未知指标')
    vals=[]
    for r in con.execute("SELECT scope, text, status, value FROM ads_kpi_value WHERE metric_id=? AND month=? AND (plant_code=? OR plant_code IS NULL) AND (shop_code=? OR shop_code IS NULL) ORDER BY plant_code NULLS FIRST, shop_code",(mid,month,plant,shop)):
        vals.append(dict(scope=r['scope'], text=r['text'], status=r['status'], value=r['value']))
    return dict(metric=dict(m), values=vals, month=month)

def update_action(con, aid, body):
    st=body.get('status'); note=body.get('note')
    row=con.execute("SELECT * FROM ads_action WHERE action_id=?",(aid,)).fetchone()
    if not row: raise BadRequest('行动项不存在')
    closed=row['closed_at']
    if st=='已关闭' and not closed:
        closed=dt.date.today().isoformat()
    if st and st!='已关闭':
        closed=None
    con.execute("UPDATE ads_action SET status=COALESCE(?,status), note=COALESCE(?,note), closed_at=? WHERE action_id=?",
                (st, note, closed, aid))
    con.commit()
    return dict(ok=True, message=f'行动项 #{aid} 已更新为「{st or row["status"]}」')

def demo_story(con, month):
    return dict(steps=[
        dict(title='集团：成本超测算', nav=dict(page='group', month=month, plant='A'),
             highlight=['kpi-unit_cost','card-pbar'],
             text='集团单车转换成本 <b>¥5,202</b>，高于 VCS 测算 <b>¥4,980（+4.5%）</b>。柱图里 A工厂最红：<b>¥5,512 vs ¥4,997（+10.3%）</b>。先点进 A工厂。'),
        dict(title='A工厂：加班与执行偏离', nav=dict(page='plant', month=month, plant='A'),
             highlight=['kpi-ot_rate','kpi-vcs_exec','card-vcs'],
             text='六项运营指标发红。加班率 <b>29.5%</b>（VCS 25.1%），VCS 方案执行率仅 <b>62%</b>。总装线体加班 96 h vs 建议 72.2 h，执行率 28%。瓶颈在总装。'),
        dict(title='总装：缺件占停线 54%', nav=dict(page='assembly', month=month, plant='A', shop='GA'),
             highlight=['kpi-ga_stop','kpi-short_cnt','card-parts'],
             text='停线 43.7 分钟/班（月 2,140 分钟 / 49 班当量）。缺件 1,155 分钟 / 86 次。Top 零件 <b>P-30117 线束总成，供应商 S07</b>。'),
        dict(title='物流：S07 准时率 76.5%', nav=dict(page='logistics', month=month, plant='A'),
             highlight=['kpi-lg_ontime','card-sup'],
             text='工厂到货准时率约 89.5%（目标 95%）。S07 76.5% 垫底，且贡献两只线束零件的缺件停线。线边缓冲整体偏紧。'),
        dict(title='VCS联动：偏差怎么拆', nav=dict(page='vcs', month=month, plant='A'),
             highlight=['kpi-cost_total','kpi-backtest','card-wf'],
             text='总额 5,699.8 万 vs 测算 5,497.0 万（+3.7%，成本阈值内），但产量 −6.0% 超 ±2%。单车 +10.3% 里，产量摊薄 +319 元，花费偏差 +196 元。PBS 缓存已满。'),
        dict(title='行动闭环', nav=dict(page='actions', month=month, plant='A'),
             highlight=['card-ac'],
             text='预警已自动生成待办：物流经理盯 S07 与缺件，计划经理复盘总装偏离 VCS 方案，财务在经营会把单车成本列为红色议题。演示结束。全部为示例数据。'),
    ])

def vcs_simulate(con, q):
    S=load_story()
    vol=int(q.get('vol') or 0); wage=int(q.get('wage') or 0); elec=int(q.get('elec') or 0)
    strat=q.get('strategy') or 'cost'
    # annual pack baseline 43433 / 3619
    base_tot, base_u = 43433, 3619
    # elasticities from scenarios: +10% demand -> 46366 / 3513; -10% 40126 / 3715; elec+20% 44240; wage+5% 44278
    tot = base_tot * (1 + vol/100*0.67) * (1 + wage/100*0.39) * (1 + elec/100*0.093)
    # volume effect on unit: +10% vol -> unit -2.9%
    unit = base_u * (1 + vol/100*(-0.29)) * (1 + wage/100*0.39) * (1 + elec/100*0.093)
    prem = 0.0 if strat=='cost' else 0.044
    tot *= (1+prem); unit *= (1+prem)
    option=dict(xAxis=dict(type='category',data=['年度转换成本（万元）']),
                yAxis=dict(type='value'),
                series=[dict(name='基准',type='bar',data=[base_tot]),
                        dict(name='情景',type='bar',data=[round(tot)])])
    table=dict(kind='table', columns=[{'name':'项'},{'name':'基准','num':True},{'name':'情景','num':True},{'name':'变化'}],
               rows=[['年度转换成本（万元）', f'{base_tot:,}', f'{tot:,.0f}', f'{(tot-base_tot)/base_tot*100:+.1f}%'],
                     ['单车成本（元）', f'{base_u:,}', f'{unit:,.0f}', f'{(unit-base_u)/base_u*100:+.1f}%'],
                     ['策略溢价', '成本优先 0%', ('稳定优先 +4.4%' if strat!='cost' else '0%'), ''],
                     ['说明', '年度基准包口径', '线性示意，非求解器', '与月度 FULL_COST 不同（评审 C1）']])
    return dict(option=option, table=table, note='示例')

PAGE_FN = {
    'group': page_group, 'plant': page_plant, 'stamping': page_shop('ST','冲压'), 'body': page_shop('BD','焊装'),
    'paint': page_shop('PT','涂装'), 'assembly': page_shop('GA','总装'), 'quality': page_quality,
    'logistics': page_logistics, 'energy': page_energy, 'workforce': page_workforce, 'vcs': page_vcs,
    'cost': page_cost, 'plan': page_plan, 'maint': page_maint, 'safety': page_safety, 'governance': page_gov,
    'registry': page_registry, 'actions': page_actions, 'rootcause': page_root, 'benchmark': page_bench,
}
