"""Airflow DAG 示例（不必安装/运行 Airflow）。生产形态：
MES/ERP/WMS/QMS/EMS/HR/VCS → 本 DAG → 华为云数仓 ODS/DWD/DWS/ADS → Power BI。
演示环境用 etl/local_runner.py 跑同一套脚本。
"""
from datetime import datetime
try:
    from airflow import DAG
    from airflow.operators.bash import BashOperator
    import os
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    with DAG(
        dag_id='control_tower_daily',
        start_date=datetime(2026, 1, 1),
        schedule='15 2 * * *',
        catchup=False,
        tags=['control-tower', 'example-data'],
        doc_md='每日构建 Manufacturing Control Tower ADS（示例项目）。',
    ) as dag:
        py = f'cd {ROOT} && python3'
        extract = BashOperator(task_id='extract_sources', bash_command=f'{py} -m etl.generate_sources')
        transform = BashOperator(task_id='build_dwd_dws_ads', bash_command=f'{py} -c "from etl.transform import transform; transform()"')
        export = BashOperator(task_id='export_pack', bash_command=f'{py} -m etl.export_pack')
        extract >> transform >> export
except ImportError:
    dag = None  # 本地无 Airflow 时仅作为文档与结构示例
