# CHANGELOG - 二开改动记录

本文件记录所有二次开发的改动，与原始 Grok2API v1.6.2 的差异。

---

## [1.7.0] - 2026-04-09

### Changed

- **`POST /v1/videos` 改为异步任务模式**
  - 原行为：客户端发请求后同步等待数分钟，直到视频生成完毕才返回结果
  - 新行为：立刻返回 `task_id`（HTTP 202），客户端通过轮询获取进度和结果
  - 文件：`app/api/v1/video.py` — `_create_video_from_payload()` 函数重写为异步提交
  - 文件：`app/api/v1/video.py` — 新增 `_run_video_task()` 后台执行函数

- **`docker-compose.yml` 启用 Warp + FlareSolverr**
  - 原行为：Warp 和 FlareSolverr 服务被注释掉，CF 环境变量被注释掉
  - 新行为：三个服务全部启用，grok2api 依赖 warp 和 flaresolverr
  - 镜像从 `ghcr.io/chenyme/grok2api:latest`（官方）改为 `build: .`（本地构建）
  - 新增 `depends_on: warp, flaresolverr`

- **`config.defaults.toml` 代理配置启用**
  - `proxy.base_proxy_url`: `""` → `"socks5://warp:1080"`（走 Warp 出口）
  - `proxy.enabled`: `false` → `true`（启用 CF 自动刷新）

### Added

- **`GET /v1/videos/{task_id}` 查询视频生成进度和结果**
  - 返回任务状态：`pending` / `running` / `completed` / `failed`
  - 生成中返回实时进度（如 `[round=1/2] progress=45%`）
  - 完成后返回完整视频响应（含 `video_url`，格式与原接口一致）
  - 任务 1 小时后自动过期清理
  - 文件：`app/api/v1/video.py` — `get_video_task_status()` 路由

- **`app/core/video_task.py` 视频任务池管理模块**
  - `VideoTask` 数据结构：任务状态、进度、结果、错误信息
  - 内存任务池，最多保留 1000 个任务，自动清理过期任务
  - 函数：`create_video_task()` / `get_video_task()` / `expire_video_task()`

### Unchanged (未改动)

- `app/services/grok/services/video.py` — VideoService 核心生成逻辑未改动
- `app/services/reverse/` — 反向代理层未改动
- `app/services/token/` — Token 池管理未改动
- `main.py` — 应用入口和路由注册未改动
- `POST /v1/video/extend` — 视频续生接口未改动
- `POST /v1/chat/completions` (model=grok-imagine-1.0-video) — Chat 接口的视频路径未改动

---

## API 使用示例

### 提交视频生成任务

```bash
curl -X POST https://your-domain/v1/videos \
  -H "Authorization: Bearer <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "3D 玄幻动漫风格，龙角女子在深海幽潭中...",
    "seconds": 15,
    "quality": "high",
    "size": "1280x720"
  }'

# 立刻返回（HTTP 202）：
# {"task_id": "vtask_a1b2c3d4e5f67890", "status": "pending"}
```

### 轮询查询进度

```bash
curl https://your-domain/v1/videos/vtask_a1b2c3d4e5f67890 \
  -H "Authorization: Bearer <your-api-key>"

# 生成中：
# {"task_id": "vtask_...", "status": "running", "progress": "[round=1/2] progress=45%", ...}

# 完成后：
# {"task_id": "vtask_...", "status": "completed", "result": {"id": "video_...", "url": "https://...", ...}}

# 失败：
# {"task_id": "vtask_...", "status": "failed", "error": "No available tokens"}

# 任务不存在或已过期：
# HTTP 404: {"error": {"message": "Video task 'vtask_...' not found or expired", ...}}
```
