# 鹿小仓 — 任务看板

> 最后更新：2026-07-19 15:35  
> 维护者：WorkBuddy Agent  
> 路线图依据：`docs/鹿小仓AI经营Agent全周期落地路线图_v2.1_20260715.md`

> ⚠️ **【硬约束优先】** 执行任何任务前，**必须先阅读 `WORKFLOW_MANDATORY.md`**。
> 该文件定义了每次代码改动必须走的 5 步链路（本地测试→GitHub备份→云端部署→线上验证→变更记录），缺一不结。

---

## ✅ 已完成

### 阶段1（v0.1 → v0.5.4）— 基础框架

| 编号 | 任务 | Commit | 说明 |
|------|------|--------|------|
| — | 多租户架构 + 三层RBAC | — | admin/manager/store_owner 角色体系 |
| — | 任务系统 | — | 下发/接收/上传/解析闭环 |
| — | 比价矩阵 | — | 竞品价格对比 |
| — | 审计日志 | — | 操作记录 |
| — | E2E测试 | — | e2e_test.py 26/27通过 |
| — | 前端单页应用 | — | static/index.html |

### 阶段2 — 中期迭代（已完成的子任务）

| 编号 | 任务 | Commit | 完成日期 | 说明 |
|------|------|--------|---------|------|
| D2-01 | 巡检引擎 | — | 2026-07-15 | 定时巡检 price_data，异常写入 message_queue |
| D2-02 | 消息中心UI | `4e9d711` | 2026-07-16 | 三级告警/级别筛选/标记已读/全部已读/立即巡检/60s轮询 |
| D2-03 | 视频采集闭环 | — | 2026-07-15 | 视频上传→OCR解析→price_data入库 |
| D2-05 | AI主动咨询对话 | `0e37638` | 2026-07-16 | 主动开场+告警注入system prompt+快捷操作芯片 |
| F1 | 审计补全 | — | 2026-07-15 | 补齐缺失的审计日志 |
| F2 | 价格鲁棒化 | — | 2026-07-15 | _upsert_price INSERT OR REPLACE |
| F4 | 截止日期修复 | `ee4c6a8` | 2026-07-15 | deadline解析校验 |
| — | 仓库清理 | `0e37638` | 2026-07-16 | 删除30个临时脚本，.gitignore加`_*`规则 |
| D2-06 | 选品规划+商品分层 | `bebaed2` | 2026-07-16 | 4大分析引擎+5个API+4个Agent工具 |
| D2-07 | 数据看板可视化 | `686ea58` | 2026-07-16 | ECharts看板+单店/总部双视图+角色隔离+static挂载 |
| D2-09 | 门店画像&长期记忆 | `a23c4a2` | 2026-07-16 | memory.py + store_profiles/agent_memory两表 + 对话前召回注入system prompt + 对话后流式LLM抽取写回 + /api/memory/summary端点；线上验证V2-08/V2-09通过(一次诊断对话写回4画像+4记忆) |
| D2-08 | 用户偏好学习 | `281d453` | 2026-07-16 | query_stats表 + classify_query(确定性关键词分类,不调LLM) + record_query(对话时记录) + get_top_preferences + build_preference_context(连续5次同类型后注入system prompt) + /api/memory/preferences端点；线上验证V2-07通过 |
| 建店引擎 | 建店规划引擎 | `bc5834a` | 2026-07-16 | build_store.py(面积→品类权重→SKU推算→货架方案,纯逻辑启发式,默认参数集中可校准) + /api/build_store/plan端点 + agent_loop build_store_plan工具；自测(50/100/200㎡+面积=0异常)全过 + 线上验证(area=100返回完整方案/area=0返回400)通过 |
| D2-11 | 内部数据采集接入(路线A) | `c2ec8bf` | 2026-07-16 | ingestion.py + raw_orders/raw_reviews/raw_items/import_batches四表 + 灵活中英文列映射解析(美团原生导出) + 真实GMV/毛利/动销率聚合 + 手动Excel/CSV导入端点 + 导入历史 + 模板下载 + 前端数据导入视图；线上验证通过(合成美团xlsx→4行入库→看板data_mode切real,GMV22/订单3/AOV7.33) |
| 盈利引擎 | 动态盈利决策引擎 | `35c4dbc` | 2026-07-19 | profit_tools.py(4工具:evaluate_order/get_store_dashboard/simulate_price_change/simulate_delivery_strategy) + dynamic_profit_engine.py(配送费模型/保本计算/红线阈值) + SQLite WAL模式解决Windows文件锁 + 集成测试全过 + GitHub push + SFTP部署 + 服务重启成功；线上验证：OrderFeedItem字段名修复(name→sku_name等)，guangan门店关联正常，ingest接口200返回净利5.36元 ✅ |
| 竞品情报 | 竞品情报分析引擎 | `0cdc4c2` | 2026-07-19 | intelligence_tools.py(5工具:map_competitor_sku/compare_price_matrix/reverse_engineer_strategy/generate_counter_strategy/detect_market_gap) + competitor_intelligence_skill/(5文件) + app.py新增5张竞品数据表(competitor_stores/competitor_skus/competitor_promotions/sku_mappings/strategy_analyses) + System Prompt合并(总会计师+情报分析官双人格) + 集成测试5/5通过 + GitHub push + SFTP部署 + 服务重启成功；线上验证9工具全部注册成功 |

---

## 🔄 下一步（按优先级排序）

| 优先级 | 编号 | 任务 | 预估 | 类型 | 依赖 | 说明 |
|--------|------|------|------|------|------|------|
| P0 | D2-09 | 门店画像&长期记忆 | 3天 | 后端 | 无 | ✅ 已完成（线上验证通过 V2-08/V2-09） |
| P1 | D2-08 | 用户偏好学习 | 2天 | 后端 | D2-09 | ✅ 已完成（线上验证通过 V2-07，确定性关键词分类，不增加LLM负担） |
| P2 | D2-11 | 内部数据采集接入 | 3天 | 后端 | 无 | ✅ 已完成（路线A：手动导入，零风控风险；线上验证通过；后续可升级RPA自动抓取） |
| P0 | — | 盈利引擎线上验证修复 | 1小时 | 后端 | 无 | ✅ 已完成（OrderFeedItem字段名修复，guangan关联正常，线上验证通过） |
| P1 | — | 竞品情报数据初始化 | 2小时 | 数据 | 竞品情报引擎 | 按 data_collection_checklist.md 采集竞品数据，录入真实竞品门店数据 |
| P2 | — | 双 Skill 协同端到端测试 | 3小时 | 后端 | 数据初始化 | 用真实数据测试"对手在做什么+我们的底线在哪=我们该怎么做"完整决策链路 |
| P3 | — | 三端关系梳理 | 2小时 | 文档 | 无 | 商家端(小程序)/云端(阿里云ECS)/本机(WorkBuddy) 关联关系文档化 |
| P2 | D2-04 | 小程序核心页面 | 7天 | 前端 | 微信注册 | 首页/任务页/AI咨询页/我的 |
| P2 | D2-10 | 微信小程序上线 | 3天 | 运维 | D2-04 | 提交审核+域名白名单+灰度发布 |
| P2 | — | 选址评估工作流 | — | 后端 | 无 | 高德API→POI扫描→竞品密度→评分 |


---

## 📋 阶段3（45天+）— 商用·自主决策

| 编号 | 任务 | 预估 | 说明 |
|------|------|------|------|
| D3-01 | 自主决策引擎 | 10天 | 感知→方案→评估→审批→执行→追踪→优化 |
| D3-02 | 经营规划引擎 | 5天 | 月度目标→周度分解→每日巡检→偏离预警 |
| D3-03 | 供应链智能接管 | 8天 | 库存同步+安全库存+智能补货+供应商比价+跨店调拨 |
| D3-04 | 美团数据自动接入 | 5天 | 美团API/爬取→自动更新竞品价格 |
| D3-05 | 多门店协同调度 | 5天 | 跨店调拨+新品试点推荐+促销适配评估 |
| D3-06 | 财务管理自动核算 | 5天 | 收入成本汇总+损益表+ROI计算 |
| D3-07 | 独立运维后台 | 5天 | 独立运维面板+ops角色 |
| D3-08 | 数据安全审计达标 | 3天 | 脱敏+水印+日志备份 |

---

## 🔑 关键信息

| 项目 | 值 |
|------|------|
| GitHub | `ecodrive911-LTJ/luxiaocang-store-agent` (master→main) |
| 阿里云 | `120.26.176.215` `/opt/luxiaocang/` (root/DOWson1108) |
| 部署 | `python upload_to_server.py`（需paramiko，系统Python3.12有） |
| admin | `luxiaocang / LXC2025` |
| store_owner | `guangan / guangan123` |
| 路线图 | `docs/鹿小仓AI经营Agent全周期落地路线图_v2.1_20260715.md` |
| 凭证 | `CREDENTIALS.md` |
| 本地目录 | `C:\Users\13522\diancanmou\` |

---

## 📝 变更记录

- **2026-07-16**：创建任务看板。阶段1全部完成，阶段2已完成D2-01/D2-02/D2-03/D2-05/F1/F2/F4。下一步：D2-06选品规划、D2-07数据看板。
- **2026-07-16**：D2-06完成。新增product_analysis.py(453行)+5个API端点+4个Agent工具。下一步：D2-07数据看板。
- **2026-07-16**：D2-07完成。新增analytics.py(307行)+2个聚合API+ECharts看板前端。修复require_auth的user键(user_id非id)。下一步：D2-09门店画像。
- **2026-07-16**：D2-09门店画像&长期记忆已实现（代码层）。新增memory.py（召回build_memory_context + 对话后LLM抽取写回extract_and_save_memory + 查询get_memory_summary）；app.py的init_db新增store_profiles/agent_memory两表（store_id TEXT匹配UUID）；chat与proactive_opening端点注入画像上下文；对话结束触发抽取写回。新增GET /api/memory/summary。逻辑自测(_test_memory.py)全过。待部署阿里云+真实对话验证V2-08/V2-09。下一步：D2-08用户偏好学习。
- **2026-07-16**：D2-09线上验证+修复。初版抽取用非流式call_llm_raw(timeout=90)且prompt schema与解析器不匹配→真实对话写回0条。修复：①抽取改用流式call_llm_stream(首token秒回，整体~30s vs 非流式~90s，快3倍)；②重写抽取prompt强制严格键名(profile_type/content/confidence、memory_type/summary/importance)并禁止其它键名；③解析器加类型归一化(_PROFILE_TYPE_ALIAS/_MEMORY_TYPE_ALIAS)容忍id/type/name/subject_id等异构键；④持久化(save_message+抽取)改为脱离请求生命周期的asyncio后台任务，客户端SSE超时/刷新断开也不丢记忆。线上验证：一次诊断对话(405字)→抽取写回4画像+4记忆(V2-09 PASS)，二次对话召回注入正常(V2-08 PASS)。下一步：D2-08用户偏好学习。
- **2026-07-16**：D2-08用户偏好学习完成(commit待填)。新增query_stats表(store_id/category/topic/count唯一约束)；memory.py加classify_query(确定性中文关键词分类问题类型+品类/门店主题，不调LLM避免端点限流)、record_query(对话时累加计数)、get_top_preferences(>=阈值返回)、build_preference_context(连续5次同类型后生成偏好引用块)；app.py在chat端点save_message后record_query，并把preference_context拼入system prompt，新增GET /api/memory/preferences。线上验证V2-07：发1次定价对话确认record_query接线(计数=1)，补种到5后第2次对话AI回复优先聚焦定价(可口可乐错价)，偏好注入生效。清理测试数据。下一步：剩余后端任务(D2-06/07/08/09)均已完成，仅剩小程序相关(D2-04/D2-10)需微信注册等外部依赖
- **2026-07-16**：建店引擎完成(commit bc5834a)。新增build_store.py(面积→品类权重→SKU推算→货架方案,纯启发式,默认参数集中可校准)+app.py /api/build_store/plan端点+agent_loop build_store_plan工具；自测(50/100/200㎡+面积=0异常分支)全过；部署阿里云+线上验证(area=100返回完整方案,area=0返回400)通过；已git push origin master:main备份。下一步：建店引擎参数权重后续按真实门店数据校准；剩余仅小程序相关(D2-04/D2-10)需微信注册等外部依赖。
