import os, sys, json
from etl.common import connect, STORY_MONTH
from app import api as A

def call(path, role='group', q=None, method='GET', body=None):
    con = connect()
    q = q or {'month': STORY_MONTH, 'plant': 'A', 'shop': 'GA'}
    code, res = A.route(con, method, path, q, body or {}, role)
    con.close()
    return code, res

def test_health_and_meta():
    code, res = call('/api/health')
    assert code == 200 and res['ok'] and res['label']=='EXAMPLE-DATA'
    code, res = call('/api/meta')
    assert code == 200 and res['default_month']==STORY_MONTH
    assert any(p['id']=='vcs' for p in res['pages'])

def test_group_and_vcs_pages():
    code, res = call('/api/page/group')
    assert code == 200 and res['kpis']
    assert any(k['metric_id']=='unit_cost' for k in res['kpis'])
    code, res = call('/api/page/vcs')
    assert code == 200
    assert 'VCS' in res['title'] or 'VCS' in res['subtitle']

def test_rls_forbidden():
    try:
        call('/api/page/group', role='plant_A')
        assert False, 'should forbid'
    except A.Forbidden:
        pass
    code, res = call('/api/page/plant', role='plant_A', q={'month':STORY_MONTH,'plant':'A','shop':'GA'})
    assert code == 200
    try:
        call('/api/page/plant', role='plant_A', q={'month':STORY_MONTH,'plant':'B','shop':'GA'})
        assert False
    except A.Forbidden:
        pass

def test_metric_and_story():
    code, res = call('/api/metric/unit_cost')
    assert code == 200 and res['metric']['name']
    code, res = call('/api/story')
    assert code == 200 and len(res['steps']) >= 5

def test_simulate_and_action():
    code, res = call('/api/vcs/simulate', q={'vol':'10','wage':'0','elec':'0','strategy':'cost','month':STORY_MONTH,'plant':'A'})
    assert code == 200 and 'option' in res
    con = connect()
    aid = con.execute("SELECT action_id FROM ads_action LIMIT 1").fetchone()['action_id']
    con.close()
    code, res = call(f'/api/actions/{aid}', method='POST', body={'status':'处理中','note':'pytest'})
    assert code == 200 and res['ok']


def test_plant_page_story():
    code, res = call('/api/page/plant', q={'month':STORY_MONTH,'plant':'A','shop':'GA'})
    assert code == 200 and not res.get('error')
    assert '工厂' in res['title']
    assert len(res['kpis']) >= 6
    texts = ' '.join(str(k.get('text') or k.get('value') or '') for k in res['kpis'])
    assert '29.5' in texts or any('29.5' in str(k) for k in res['kpis'])
    assert '81.2' in texts or any('81.2' in str(k) for k in res['kpis'])
