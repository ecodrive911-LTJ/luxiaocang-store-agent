# 店参谋 — 独立Web应用架构

## 技术选型

### 前端
- 纯HTML + CSS + JS（无框架依赖，首屏即用）
- 深色主题，对话驱动交互
- SSE（Server-Sent Events）接收Agent流式回复

### 后端
- Python FastAPI（轻量、异步、自带文档）
- Uvicorn ASGI服务器
- 端口 8420（不易冲突）

### 大模型
- 独立API Key直调（用户自行配置）
- 支持：智谱GLM / OpenAI兼容接口 / DeepSeek
- 后端代理调用，Key不存在前端

### 数据存储
- SQLite（轻量、无需安装数据库服务）
- 文件目录：~/diancanmou/

### 采集引擎
- Playwright（独立安装，不依赖QClaw的xbrowser）
- 后台浏览器自动化

## 目录结构

```
C:\Users\13522\diancanmou\
├── app.py              # FastAPI主程序
├── config.ini          # 配置文件（API Key等）
├── database.db         # SQLite数据库
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

| 路径 | 方法 | 功能 |
|------|------|------|
| / | GET | 主页面 |
| /api/chat | POST | 发送消息（SSE流式回复） |
| /api/status | GET | Agent状态 |
| /api/data/assets | GET | 数据资产列表 |
| /api/collect/start | POST | 启动采集任务 |
| /api/collect/status | GET | 采集任务状态 |
| /api/config | GET/PUT | 读取/更新配置 |
