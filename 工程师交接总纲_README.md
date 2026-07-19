# 鹿小仓·店参谋 工程师交接总纲 v2.0

> 创建时间：2026-07-15 23:50 | 当前阶段：**阶段2 进行中**（v2.1路线图）  
> 最新版本：v0.5.4+（融合版 commit `236871c`，F4 fix `ee4c6a8`）  
> 阿里云 PID：129346  
> 目标读者：任何接手此项目的工程师（前端/后端/AI/运维）  
> **阅读本文件即可完整交接**

> ⚠️ **【硬约束优先】** 在动手任何改动前，**必须先阅读 `WORKFLOW_MANDATORY.md`**。
> 该文件定义了每次代码改动必须走的 5 步链路（本地测试→GitHub备份→云端部署→线上验证→变更记录），缺一不结。
> 本文件及其他文档均不得与该硬约束冲突。

---

## 一、项目概况（30秒理解）

**项目名**：鹿小仓·店参谋（luxiaocang-store-agent）  
**定位**：便利店AI经营决策Agent，覆盖选址→建店→选品→定价→供应链→运营→品牌→促销→财务全生命周期  
**品牌方**：鹿小仓便利店（2家门店：广安店/财富店，河北承德）  
**技术栈**：Python 3.10 FastAPI + SQLite + 单页面前端 + Qwen/DeepSeek/火山引擎LLM + RapidOCR + ffmpeg  
**代码仓库**：GitHub `ecodrive911-LTJ/luxiaocang-store-agent`（本地分支 master → 远程 main）  
**开发现状**：阶段1（全量完成）→ 阶段2 进行中（已完成 D2-01/D2-3/D2-02/F1/F2/F4）

---

## 二、代码存放位置（4个关键路径）

| 用途 | 路径 | 说明 |
|------|------|------|
| **本地开发目录** | `C:\Users\13522\Desktop\diancanmou\`（注：实际为 `C:\Users\13522\diancanmou`） | Git仓库根目录，所有源码+文档 |
| **GitHub仓库** | `https://github.com/ecodrive911-LTJ/luxiaocang-store-agent` | 远程备份（国内网络有时443封禁） |
| **阿里云服务器** | `120.26.176.215` → `/opt/luxiaocang/` | 生产环境，FastAPI运行在这里 |
| **AI Agent配置** | `C:\Users\13522\.qclaw\workspace\luxiaocang\` | OpenClaw Agent配置文件（SOUL.md / AGENTS.md / USER.md） |

---

## 三、服务器连接信息

```
IP: 120.26.176.215
SSH: root / DOWson1108
端口: 22

服务管理:
  systemctl status luxiaocang       # 查看服务状态
  systemctl restart luxiaocang      # 重启服务（重启后等3秒再访问）
  journalctl -u luxiaocang -n 50    # 查看最近50行日志
  journalctl -u luxiaocang -f       # 实时跟踪日志

服务文件: /etc/systemd/system/luxiaocang.service
代码目录: /opt/luxiaocang/
  ├── app.py               # FastAPI主服务（融合版，~1200行）
  ├── agent_loop.py         # Agent引擎（~330行，含Path修复版本）
  ├── auth.py               # 三层RBAC认证（admin/manager/store_owner）
  ├── database.db           # SQLite数据库（13张业务表）
  ├── config.ini            # 配置文件（API密钥等）
  ├── static/index.html     # 前端单页面（含D2-02消息中心 ~56KB）
  └── scripts/
      ├── analyze_video.py  # 视频分析（D2-3: 抽帧→OCR→提价）
      ├── competitive_analysis.py
      ├── video_pipeline.py
      └── ...

访问地址: http://120.26.176.215
默认管理员: luxiaocang / LXC2025

演示门店账号:
  - guangan / guangan123（store_owner → 广安店）
  - caifu / caifu123（store_owner → 财富店）
```

---

## 四、数据库表结构（database.db，共13张表）

| 表名 | 用途 | 状态 |
|------|------|------|
| `users` | 用户账户（含role: admin/manager/store_owner） | ✅ 3条预置 |
| `stores` | 门店信息（广安/财富） | ✅ 2条 |
| `user_stores` | 用户-门店绑定 | ✅ 2条 |
| `sessions` | 登录会话 | ✅ 动态 |
| `conversations` | AI对话历史 | ✅ 有数据 |
| `collect_tasks` | 采集任务 | ✅ |
| `collect_task_items` | 任务明细 | ✅ |
| `collect_uploads` | 上传文件记录 | ✅ |
| `price_data` | **价格数据/比价矩阵**（F2修复：INSERT ON CONFLICT） | ✅ **有数据** |
| `audit_log` | 审计日志（F1：8类操作埋点+查询API） | ✅ |
| `message_queue` | **巡检异常消息/消息中心**（D2-01+D2-02，含level/title/body/is_read） | ✅ |
| `tasks` | 任务系统（D2-01延伸） | ✅ |
| `task_items` | 任务项 | ✅ |

---

## 五、API 接口速查

| 接口 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/health` | GET | 无 | 健康检查 |
| `/api/auth/login` | POST | 无 | 登录→返回token |
| `/api/auth/register` | POST | admin | 注册新用户 |
| `/api/auth/logout` | POST | 需登 | 注销 |
| `/api/chat` | POST | 需登 | AI对话（store_owner自动绑定本店） |
| `/api/data/assets` | GET | 需登 | 数据资产（store_owner仅本店） |
| `/api/stores` | GET | 需登 | 门店列表 |
| `/api/stores` | POST | admin/manager | 新增门店 |
| `/api/users` | GET | admin | 用户列表 |
| `/api/tasks` | GET/POST | 需登 | 任务列表/创建 |
| `/api/tasks/{id}/upload` | POST | 需登 | 上传采集文件 |
| `/api/uploads/{id}` | GET | 需登 | 查看上传详情 |
| `/api/uploads` | GET | 需登 | 上传记录列表 |
| `/api/audit/logs` | GET | admin/manager | 审计日志查询 |
| `/api/review/uploads` | GET | admin/manager | **上传复核界面**（D3-1） |
| `/api/review/confirm` | POST | admin/manager | **确认复核→写入price_data**（F2修复含upsert） |
| `/api/review/retry/{id}` | POST | admin | **重试AI分析**（D2-4） |
| `/api/prices/compare` | GET | 需登 | **比价矩阵**（D3-2，同商品跨店/市场均价/三档定价） |
| `/api/prices/suggest` | GET | 需登 | 定价建议 |
| `/api/inspection/run` | POST | admin/manager | **D2-01巡检引擎**手动触发 |
| `/api/inspection/status` | GET | 需登 | 巡检状态/最新扫描时间 |
| `/api/messages` | GET | admin/manager | **D2-02消息中心**（未读消息列表） |
| `/api/messages` | POST | admin | 写入消息（给message_queue表） |
| `/api/video/analyze` | POST | admin/manager | **D2-3视频分析**（异步→price_data自动写入） |
| `/api/video/analysis_status/{id}` | GET | 需登 | 视频分析状态（pending/success/failed） |

---

## 六、当前开发进度（2026-07-15 23:50）

### 已完成概览

#### 🟢 阶段1（全量完成）
| 任务 | 说明 | 状态 |
|------|------|------|
| D1-1 | 前端RBAC动态渲染（三角色不同界面） | ✅ |
| D1-2 | 后端API角色隔离（数据资产/门店/用户） | ✅ |
| D1-3 | `agent_loop.py` Path未导入 Bug 修复 | ✅ |
| D1-4 | store_owner对话自动绑定本店，竞品数据过滤 | ✅ |
| D1-5 | 全局审计日志（8类操作埋点+查询API） | ✅ |
| D2-1 | 上传校验强化+后端异步AI分析+失败重试 | ✅ |
| D2-2 | 视频上传异步解析（已升级为D2-3全链路） | ✅ |
| D2-3 | 视频上传→AI抽帧OCR→提价→写入闭环 | ✅（真实视频需验证） |
| D2-4 | 上传重试机制 | ✅ |
| D3-1 | 人工复核界面（upload review API） | ✅ |
| D3-2 | 比价矩阵+三档定价 | ✅ |
| D3-3 | E2E 自动化测试（26/27通过） | ✅ |
| 阶段性E2E | 端到端全链路验证 | ✅ |

#### 🟡 阶段2（进行中）
| 任务 | 说明 | 状态 |
|------|------|------|
| **D2-01** | **AI主动巡检引擎**（`message_queue`表+每小时调度/手动端点） | ✅ |
| **D2-3** | **视频分析全链路闭环**（抽帧→OCR→提价→自动写入`price_data`，无需confirm） | ✅（合成视频验证通过） |
| **D2-02** | **消息中心UI**（前端按钮+RBAC+Modal+防XSS+全链路验证） | ✅ **刚完成** |
| F1 | `create_task`审计日志缺失修复（远程合并获得） | ✅ |
| F2 | `confirm_upload_review`不写入`price_data`修复（INSERT ON CONFLICT REPLACE） | ✅ |
| F3 | ffmpeg缺失 → 实为误判（ffmpeg一直存在4.4.2） | ✅（澄清） |
| F4 | deadline字段ISO字符串与时间戳兼容修复 | ✅（commit ee4c6a8） |
| D2-02 真实验证 | 真实货架照片OCR准确率验证 | ⏳ |
| Git push | 本地commit ee4c6a8因网络443阻塞未推送 | ⏳ |

### 待修复/待办
- 🕐 Git push ee4c6a8（443封禁，需代理或换时段重试）
- 🕐 D2-3 真实验证OCR准确率（上传真实货架照片而非合成视频）
- 🕐 30+未跟踪临时脚本（部分已清理至 `_trash/`）

---

## 七、开发工作流

### 本地开发 → GitHub 推送
```powershell
# 在diancanmou目录下
$env:GIT_TERMINAL_PROMPT="0"
git add .
git commit -m "描述"
git push origin master:main   # ⚠️ 本地master→远程main映射
```

### 部署到阿里云
```bash
# 方式1: SFTP（推荐，服务器无法直连GitHub）
scp -r /本地路径/* root@120.26.176.215:/opt/luxiaocang/

# 方式2: SSH + git pull（当服务器代理可用时）
ssh root@120.26.176.215
cd /opt/luxiaocang
git pull origin main
systemctl restart luxiaocang

# 验证
curl http://localhost:8000/api/health
或浏览器打开 http://120.26.176.215
```

### 自动化验证
```bash
# 优先使用 Python 脚本直连 API 而非浏览器截图
python3 -c "
import requests, json
r = requests.post('http://120.26.176.215/api/auth/login',
    json={'username':'luxiaocang','password':'LXC2025'})
print(r.json())
"
```

---

## 八、核心架构与设计决策

- **多租户**：`users/stores/user_stores/sessions` 四张表实现数据隔离
- **权限模型**：三层 RBAC → admin（全权限）/ manager（查+录，不可改配置）/ store_owner（仅本店）
- **数据闭环**：上传 → AI分析 → `price_data` 写入（F2修复后无需手动confirm）
- **巡检引擎**：每小时 cron → 扫描 `price_data` → 异常检测 → `message_queue` 写入
- **消息中心**：`message_queue` 表 + GET API + 前端Modal（D2-02）
- **比价矩阵**：同商品跨店对比，含市场均价+定价建议（D3-2）
- **审计日志**：8类操作（create/update/delete/login/logout/upload/analysis/confirm），含用户ID+门店ID+时间戳+详情

---

## 九、已知问题与约束

| 问题 | 影响 | 状态 |
|------|------|------|
| 阿里云ECS无法直连GitHub（443封禁） | Git push/SSH代理不稳定 | ⚠️ 长期，换SFTP绕过 |
| 数据库为SQLite（非生产级） | 并发低，无主从 | ⚠️ 阶段1遗留，阶段3可能换PG |
| D2-3 OCR用合成视频验证，真实照片未测 | OCR准确率未知 | ⏳ 待验证 |
| 30+未跟踪临时脚本在 `_trash/` 中 | 可能含有用工具 | ℹ️ 新工程师可按需捡回 |
| F4 deadline校验：ISO字符串+时间戳兼容 | 已修复部署 | ✅ |
| `price_data` 依赖外部AI API（火山/DeepSeek） | API故障时影响 | ⚠️ 注意fallback |

---

## 十、文件夹文件清单

| 文件名 | 大小 | 用途 | 优先级 |
|--------|------|------|--------|
| **本文件（交接总纲）** | — | 🔴 先读这个 | ⭐⭐⭐ |
| CREDENTIALS.md | 5.5KB | 所有API密钥和账号（火山/DeepSeek/高德/GitHub/阿里云） | ⭐⭐⭐ |
| ARCHITECTURE.md | 2.4KB | 多租户架构设计文档 | ⭐⭐ |
| D2-01巡检引擎_F2修复_20260715.md | 3.8KB | 巡检引擎实现记录 | ⭐ |
| D2-3视频分析闭环验证_F3澄清_20260715.md | 3.0KB | 视频分析全链路验证记录 | ⭐ |
| 融合部署_D2-01_D2-3_F1_F2_20260715.md | 3.9KB | 远程远程融合部署记录 | ⭐ |
| 阶段1_D3完成_20260715.md | 2.5KB | 阶段1 Day3完成记录 | ⭐ |
| 阶段1执行记录_20260715.md | 4.9KB | 阶段1全过程执行记录 | ⭐ |
| app.py | ~1200行 | FastAPI主服务（融合版） | — |
| static/index.html | ~56KB | 前端单页面（含D2-02） | — |
| `_trash/` | ~20 files | 临时脚本回收站（工程师可按需恢复） | ℹ️ |

---

## 十一、版本演进摘要

| 版本 | 变更 | 日期 |
|------|------|------|
| v0.1 | 初始Demo | 7/11 |
| v0.4 | 多租户架构+RBAC | 7/12-7/13 |
| v0.5 | 任务系统+路线图 | 7/13 |
| v0.5.4 | 阶段1全量完成 | 7/15 18:59 |
| v0.5.4+ | 融合版（D2-01/D2-3/F1/F2） | 7/15 19:37 |
| ee4c6a8 | F4 deadline修复 | 7/15 22:17 |
| 融合版部署 | D2-02消息中心UI | 7/15 23:35 |

Git remote（阿里云不可达，需本机操作）：
```
origin = https://ghp_9x44E5YrDvDGFTNkTK48Z3MrYlP0YU0CQJGo@github.com/ecodrive911-LTJ/luxiaocang-store-agent
本地分支: master → 远程分支: main
```

---

## 十二、快速上手（接手工程师）

1. **连接服务器**检查现状：`ssh root@120.26.176.215` → `systemctl status luxiaocang` → `curl localhost:8000/api/health`
2. **本地获取代码**：`git clone <repo> && cd diancanmou`
3. **阅读CREDENTIALS.md**获取所有API密钥配置
4. **熟悉数据库**：`sqlite3 /opt/luxiaocang/database.db .tables`
5. **下一步工作**：
   - 尝试Git push ee4c6a8到GitHub（需网络通畅或代理）
   - D2-3 真实验证OCR准确率（上传真实货架照片）
   - 清理`_trash/`中有用脚本，删除无用文件
   - 重置测试数据（`price_data`中的合成测试数据可清理）

---

*本文件持续更新。每次里程碑更新后同步「当前开发进度」章节。*
*下一位工程师从「快速上手」开始即可。*
