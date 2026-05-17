# 主线雷达 ThemeRadar

A 股主线预警 Web 系统：盘面先热，消息后吹；资金先进，散户后跟。

## 功能

- 收盘扫描：概念板块聚合打分 + 四阶段（萌芽/发酵/高潮/衰退）
- Top5 主线榜单 + 大盘环境条
- 预警中心：新晋萌芽、阶段升级、高潮/衰退撤退
- 板块列表：全部已评分板块 + 五维得分
- 板块详情、复盘日历
- 事件驱动回测（与实盘共用 ThemeEngine）

交易策略说明见项目 Skill：`.cursor/skills/themeradar-trading/SKILL.md`（含买卖规则、已知局限与改进方向）。

## 快速开始

### Docker（推荐）

```bash
cp .env.example .env
# 可选：配置 JQDATA_USERNAME / JQDATA_PASSWORD，并设置 DEMO_MODE=false
# INGEST_MAX_CONCEPTS=0 表示入库聚宽返回的全部概念板块（首次扫描较慢）

docker compose up --build
```

- Web: http://localhost:3000
- API: http://localhost:8000/docs

首次使用：打开仪表盘 → **执行收盘扫描**。

#### Docker 拉镜像超时（`context deadline exceeded`）

多为访问 **Docker Hub**（`registry-1.docker.io`）网络不稳，常见于国内网络。

1. **配置镜像加速**（Docker Desktop → Settings → Docker Engine），在 JSON 里增加例如：
   ```json
   "registry-mirrors": [
     "https://docker.1ms.run",
     "https://docker.xuanyuan.me"
   ]
   ```
   保存后 **Apply & Restart**，再执行 `docker compose up --build`。
2. 或开启 **VPN/代理** 后重试。
3. 可先单独拉取测试：`docker pull postgres:16-alpine`，成功后再 `compose up`。

当前 compose 仅依赖 `postgres` 基础镜像（已去掉未使用的 Redis），拉取量更小。

### 本地开发

**后端**必须使用 **Python 3.11 / 3.12 / 3.13**。你当前若是 **3.14**，安装 `pydantic-core` 会报错：

`Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)`

**解决办法（任选其一）：**

1. **推荐：用 Docker**（见上文），无需本机装 Python。
2. **安装 3.12 并重建虚拟环境**（macOS + Homebrew）：

```bash
brew install python@3.12
cd backend
rm -rf .venv
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. **不推荐**：强行用 3.14 编译（可能仍失败）  
   `export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` 后再 `pip install`。

```bash
cd backend
source .venv/bin/activate   # 需已是 3.12 的 venv
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://themeradar:themeradar@localhost:5432/themeradar
export DATABASE_URL_SYNC=postgresql://themeradar:themeradar@localhost:5432/themeradar
export DEMO_MODE=true
uvicorn app.main:app --reload --port 8000
```

**前端**

```bash
cd frontend
npm install
npm run dev
```

## 数据说明

- 默认 `DEMO_MODE=true` 使用合成数据，无需聚宽账号即可演示全链路。
- 配置 [JQData](https://www.joinquant.com/help/api/doc?name=JQDatadoc&id=9842) 后设置 `DEMO_MODE=false` 与账号密码。

## 免责声明

本系统仅供个人研究，不构成投资建议。投资有风险，决策需谨慎。
