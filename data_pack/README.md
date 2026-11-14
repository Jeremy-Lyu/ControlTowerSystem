# Control Tower 数据包（示例数据）

> 全部为示例数据，可直接导入 Power BI 或 Excel。表结构与 `data/control_tower.db` 一致。

## 内容

- 各表一份 CSV（UTF-8，首行为表头）
- `Control_Tower_DataPack.xlsx`：维度、DWS、ADS 等分析常用表合订（便于直接打开）

重建：在项目根目录执行 `python3 -m etl.export_pack`。

## CSV 清单

| 文件 | 说明 |
| --- | --- |
| `ads_action.csv` | ADS 指标与应用 |
| `ads_graph_edge.csv` | ADS 指标与应用 |
| `ads_graph_node.csv` | ADS 指标与应用 |
| `ads_kpi_spark.csv` | ADS 指标与应用 |
| `ads_kpi_value.csv` | ADS 指标与应用 |
| `ads_usage_log.csv` | ADS 指标与应用 |
| `dim_account.csv` | 维度 |
| `dim_buffer.csv` | 维度 |
| `dim_date.csv` | 维度 |
| `dim_defect.csv` | 维度 |
| `dim_equipment.csv` | 维度 |
| `dim_jph_tier.csv` | 维度 |
| `dim_metric.csv` | 维度 |
| `dim_part.csv` | 维度 |
| `dim_plant.csv` | 维度 |
| `dim_shift.csv` | 维度 |
| `dim_shift_pattern.csv` | 维度 |
| `dim_shop.csv` | 维度 |
| `dim_supplier.csv` | 维度 |
| `dwd_dq_result.csv` | DWD 清洗事实 |
| `dwd_fact_andon.csv` | DWD 清洗事实 |
| `dwd_fact_attendance.csv` | DWD 清洗事实 |
| `dwd_fact_audit.csv` | DWD 清洗事实 |
| `dwd_fact_buffer.csv` | DWD 清洗事实 |
| `dwd_fact_copq.csv` | DWD 清洗事实 |
| `dwd_fact_cost.csv` | DWD 清洗事实 |
| `dwd_fact_defect.csv` | DWD 清洗事实 |
| `dwd_fact_delivery.csv` | DWD 清洗事实 |
| `dwd_fact_die_change.csv` | DWD 清洗事实 |
| `dwd_fact_downtime.csv` | DWD 清洗事实 |
| `dwd_fact_dq_hist.csv` | DWD 清洗事实 |
| `dwd_fact_energy.csv` | DWD 清洗事实 |
| `dwd_fact_hazard.csv` | DWD 清洗事实 |
| `dwd_fact_incident.csv` | DWD 清洗事实 |
| `dwd_fact_inspection.csv` | DWD 清洗事实 |
| `dwd_fact_inventory.csv` | DWD 清洗事实 |
| `dwd_fact_job_run.csv` | DWD 清洗事实 |
| `dwd_fact_lineside.csv` | DWD 清洗事实 |
| `dwd_fact_order.csv` | DWD 清洗事实 |
| `dwd_fact_oven.csv` | DWD 清洗事实 |
| `dwd_fact_plan_change.csv` | DWD 清洗事实 |
| `dwd_fact_plan_daily.csv` | DWD 清洗事实 |
| `dwd_fact_press.csv` | DWD 清洗事实 |
| `dwd_fact_production.csv` | DWD 清洗事实 |
| `dwd_fact_roster.csv` | DWD 清洗事实 |
| `dwd_fact_spare.csv` | DWD 清洗事实 |
| `dwd_fact_takt.csv` | DWD 清洗事实 |
| `dwd_fact_usage.csv` | DWD 清洗事实 |
| `dwd_fact_vcs_buffer_plan.csv` | DWD 清洗事实 |
| `dwd_fact_vcs_cost_plan.csv` | DWD 清洗事实 |
| `dwd_fact_vcs_plan.csv` | DWD 清洗事实 |
| `dwd_fact_vcs_plan_day.csv` | DWD 清洗事实 |
| `dwd_fact_vehicle_ftt.csv` | DWD 清洗事实 |
| `dwd_fact_warranty.csv` | DWD 清洗事实 |
| `dwd_fact_wo.csv` | DWD 清洗事实 |
| `dwd_vcs_scenario.csv` | DWD 清洗事实 |
| `dws_cost_account_month.csv` | DWS 汇总 |
| `dws_ga_daily.csv` | DWS 汇总 |
| `dws_group_month.csv` | DWS 汇总 |
| `dws_plant_month.csv` | DWS 汇总 |
| `dws_shop_month.csv` | DWS 汇总 |
| `ods_aps_change.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_aps_plan_daily.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_bi_usage.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_cmms_wo.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_ehs_hazard.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_ehs_incident.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_ems_daily.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_erp_cost.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_erp_order.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_erp_spare.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_hr_attendance.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_hr_roster.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_md_defect.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_md_equipment.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_md_part.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_md_plant.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_md_shop.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_md_supplier.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_andon_daily.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_buffer_daily.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_die_change.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_downtime.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_oven_daily.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_press_daily.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_shift_run.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_mes_takt_daily.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_qms_audit.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_qms_copq.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_qms_defect.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_qms_inspection.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_qms_vehicle_ftt.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_qms_warranty.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_sys_dq_history.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_sys_job_run.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_vcs_buffer_plan.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_vcs_cost_plan.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_vcs_jph_tier.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_vcs_plan_day.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_vcs_plan_month.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_vcs_scenario.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_vcs_shift_pattern.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_wms_delivery.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_wms_inventory.csv` | ODS 源镜像（含少量演示用脏数据） |
| `ods_wms_lineside.csv` | ODS 源镜像（含少量演示用脏数据） |

建议 Power BI 关系：`dim_date[date]`、`dim_plant[plant_code]`、`dim_shop[shop_code]` 连接到对应事实/汇总表；指标以 `ads_kpi_value` 为主，口径见 `dim_metric` 或仓库内 `config/metrics.yaml`。

故事月默认切片：`month = 2026-10`，工厂 `A`。目标字段为 VCS 当月测算，不是历史固定目标。