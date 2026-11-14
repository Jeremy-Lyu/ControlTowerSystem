from etl.common import connect, STORY_MONTH

def test_layers_exist():
    con = connect()
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ['ods_mes_shift_run','dwd_fact_production','dws_plant_month','ads_kpi_value',
              'dim_jph_tier','dim_shift_pattern','dwd_fact_vcs_plan','dws_cost_account_month']:
        assert t in tables, t
    assert con.execute("SELECT COUNT(*) FROM dim_jph_tier").fetchone()[0] >= 12
    assert con.execute("SELECT COUNT(*) FROM ads_kpi_value").fetchone()[0] > 100
    # dirty energy row isolated
    dirty = con.execute("SELECT COUNT(*) FROM ods_ems_daily WHERE fix_kwh<0").fetchone()[0]
    assert dirty >= 1
    leaked = con.execute("SELECT COUNT(*) FROM dwd_fact_energy WHERE fix_kwh<0 AND ot_kwh=0 AND var_kwh=0").fetchone()[0]
    assert leaked == 0
    con.close()

def test_dq_rules_recorded():
    con = connect()
    n = con.execute("SELECT COUNT(*) FROM dwd_dq_result").fetchone()[0]
    assert n >= 8
    con.close()

def test_workdays_18_in_story_month():
    con = connect()
    n = con.execute("SELECT workdays FROM dws_shop_month WHERE month=? AND plant_code='A' AND shop_code='GA'",
                    (STORY_MONTH,)).fetchone()['workdays']
    assert n == 18
    con.close()
