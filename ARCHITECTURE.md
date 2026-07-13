# 店参谋 — 独立Web应用架构

## 技术选型

### 前端
- 纯HTML + CSS + JS（无框架依赖，首屏即用）
- 深色主题，对话驱动交互
- SSE（Server-Sent Events）接收Agent流式回复
- v0.4: 多租户架构，支持多用户多门店

### 后端
- Python FastAPI（轻量、异步、自带文档）
- Uvicorn ASGI服务器
- 端口 8420（不易冲突）
- bcrypt 密码哈希
- Session Token 认证

### 大模型
- 独立API Key直调（用户自行配置）
- 支持：智谱GLM / OpenAI兼容接口 / DeepSeek
- 后端代理调用，Key不存在前端

### 数据存储
- SQLite（轻量、无需安装数据库服务）
- 多租户：单数据库 + user_id/store_id 字段隔离
- 文件目录：~/diancanmou/

### 采集引擎
- Playwright（独立安装，不依赖QClaw的xbrowser）
- 后台浏览器自动化

## 目录结构

```
C:\Users\13522\diancanmou\
├── app.py              # FastAPI主程序（多租户v0.4）
├── auth.py             # 认证与权限模块
├── agent_loop.py       # Agent Loop引擎
├── config.ini          # 配置文件（API Key等）
├── database.db         # SQLite数据库（含users/stores/sessions表）
├── static/
│   └── index.html      # 前端页面
├── data/               # 数据文件（Excel等）
├── scripts/            # 采集脚本
│   └── collector.py    # 竞品价格采集引擎
└── logs/               # 运行日志
```

## 启动方式

```
cd C:\Users\13522\diancanmou
python app.py
→ 浏览器打开 http://localhost:8420
```

## 核心API

| 路径 | 方法 | 功能 | 鉴权 |
|------|------|------|------|
| / | GET | 主页面 | 无 |
| /api/auth/register | POST | 用户注册 | 无 |
| /api/auth/login | POST | 用户登录 | 无 |
| /api/auth/logout | POST | 登出 | 需要 |
| /api/auth/me | GET | 当前用户信息 | 需要 |
| /api/stores | GET | 门店列表 | 需要 |
| /api/stores | POST | 添加门店 | 需要 |
| /api/stores/{id} | PUT | 修改门店 | 需要 |
| /api/stores/{id} | DELETE | 删除门店 | 需要 |
| /api/chat | POST | 发送消息（SSE流式） | 需要 |
| /api/status | GET | Agent状态 | 可选 |
| /api/data/assets | GET | 数据资产列表 | 需要 |
| /api/conversations | GET | 对话历史 | 需要 |
| /api/config | GET/PUT | 读取/更新配置 | 需要 |
| /api/tools | GET | 可用工具列表 | 无 |
