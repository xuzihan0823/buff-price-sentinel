# BUFF 价格监控

一个开源 Python 服务：每 10 分钟监控配置的 BUFF CS2 商品，保留 7 天本地价格历史，评估已持有/愿望单规则，通过兼容 OpenAI 的大语言模型（LLM）获取结构化分析，并使用 QQ 机器人官方 C2C API 推送提醒。

## 功能亮点

- 使用拆分式 YAML 配置管理 1–100 件商品，分为 `owned`（已持有）和 `wishlist`（愿望单）。
- 异步获取 BUFF 首页卖单和求购数据，支持请求限速、重试、部分数据处理，并且不会写入零价格。
- 使用 SQLite WAL 模式存储数据，保留 7 天滚动快照，并为提醒、LLM 分析和 QQ 异常记录提供更长的保留期。
- 提供 1 小时、6 小时、24 小时、3 天和 7 天的趋势摘要及数据覆盖率。
- 通过兼容 OpenAI 的 `/chat/completions` 接口进行 LLM 分析，严格校验 JSON；分析失败时安全降级为仅使用规则提醒。
- 通过 QQ 机器人官方 C2C 接口发送消息，记录异常事件，并在平台恢复正常后发送一次恢复摘要。
- 使用 Docker Compose 部署，不开放任何服务端口；生产镜像固定使用 GHCR digest。

## 5 分钟 Docker 部署

### 1. 部署前准备

服务器需要满足：

- Linux AMD64 系统（当前公开镜像暂未提供 ARM64 版本）
- Docker 与 Docker Compose v2
- 可以访问 `ghcr.io`、`buff.163.com`、QQ 机器人 API 和所使用的 LLM API

还需要准备以下信息：

- 兼容 OpenAI `/v1/chat/completions` 的接口地址、API Key 和模型名称
- QQ 机器人 `APP ID`、`Client Secret` 和接收者 `OpenID`
- 需要监控的 BUFF 商品 ID、购买价格及提醒阈值
- 可选的 BUFF Session Cookie 或 HTTP/SOCKS 代理地址

确认服务器环境：

```bash
docker --version
docker compose version
uname -m
```

`uname -m` 应输出 `x86_64`。

### 2. 获取项目并生成本地配置

```bash
git clone https://github.com/xuzihan0823/buff-price-sentinel.git
cd buff-price-sentinel

cp config/app.example.yaml config/app.yaml
cp config/items.example.yaml config/items.yaml
cp config/llm.example.yaml config/llm.yaml
cp config/notifiers.example.yaml config/notifiers.yaml
```

至少需要修改：

- `config/items.yaml`：换成自己的 BUFF 商品和提醒阈值
- `config/llm.yaml`：填写实际的 LLM 接口地址和模型名称

`owned` 与 `wishlist` 中必须合计配置 1–100 件不重复商品。示例商品仅用于说明配置格式，不建议直接用于正式监控。

### 3. 创建密钥文件

首先从最新一次成功的 [GitHub Actions 工作流](https://github.com/xuzihan0823/buff-price-sentinel/actions/workflows/ci.yml)摘要中复制完整的 `Deploy` 镜像地址，然后创建 `secrets.env`：

```dotenv
IMAGE_REF=ghcr.io/xuzihan0823/buff-price-sentinel@sha256:<digest>
LLM_API_KEY=填写你的LLM_API_KEY
QQ_APP_ID=填写你的QQ_APP_ID
QQ_CLIENT_SECRET=填写你的QQ_CLIENT_SECRET
QQ_RECIPIENT_OPENID=填写接收者OPENID
BUFF_SESSION_COOKIE=
BUFF_PROXY_URL=
TZ=Asia/Shanghai
```

设置仅当前用户可读写：

```bash
chmod 600 secrets.env
```

> `config/*.yaml`、`secrets.env`、SQLite 数据和备份目录均已被 Git 忽略，请勿提交到仓库。

### 4. 启动服务

```bash
docker compose --env-file secrets.env config
docker compose --env-file secrets.env pull
docker compose --env-file secrets.env up -d --remove-orphans
docker compose --env-file secrets.env ps
```

首次部署后，先手动执行一轮采集但不调用 LLM、不发送 QQ 消息：

```bash
docker compose --env-file secrets.env exec -T buff-sentinel \
  buff-sentinel once --config-dir /app/config --dry-run
```

然后检查健康状态和日志：

```bash
docker compose --env-file secrets.env exec -T buff-sentinel \
  buff-sentinel healthcheck --config-dir /app/config

docker compose --env-file secrets.env logs --since 20m buff-sentinel
```

测试 QQ 消息发送：

```bash
docker compose --env-file secrets.env exec -T buff-sentinel \
  buff-sentinel test-notify --config-dir /app/config
```

健康检查依赖近期的 BUFF 快照。全新安装在首次成功采集前可能暂时显示 `starting` 或 `unhealthy`，不一定表示容器启动失败。

## Windows 10/11 使用方法

当前发布的是 `linux/amd64` 容器镜像，但普通 Intel/AMD 处理器的 Windows 10/11 电脑可以通过 **Docker Desktop + WSL 2** 正常拉取并运行。它不是 Windows 原生容器，Docker Desktop 必须使用 Linux 容器模式。

### 1. 安装运行环境

1. 安装并启用 [WSL 2](https://learn.microsoft.com/windows/wsl/install)。
2. 安装 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)。
3. 安装 Docker Desktop 时选择使用 WSL 2 后端。
4. 启动 Docker Desktop，等待界面显示 Docker Engine 正在运行。

在 PowerShell 中检查：

```powershell
wsl --status
docker version
docker compose version
docker info --format '{{.OSType}}/{{.Architecture}}'
```

Docker 信息应显示 Linux 容器，例如：

```text
linux/x86_64
```

如果显示 Windows 容器，请在 Docker Desktop 菜单中切换到 **Linux containers**。

### 2. 下载项目并生成配置

在 PowerShell 中执行：

```powershell
git clone https://github.com/xuzihan0823/buff-price-sentinel.git
Set-Location buff-price-sentinel

Copy-Item config/app.example.yaml config/app.yaml
Copy-Item config/items.example.yaml config/items.yaml
Copy-Item config/llm.example.yaml config/llm.yaml
Copy-Item config/notifiers.example.yaml config/notifiers.yaml
```

如果电脑没有 Git，也可以从 GitHub 项目页面选择 **Code → Download ZIP**，解压后在该目录打开 PowerShell。

使用 VS Code、记事本或其他文本编辑器修改：

- `config/items.yaml`
- `config/llm.yaml`
- 必要时修改 `config/app.yaml` 和 `config/notifiers.yaml`

### 3. 创建 `secrets.env`

在项目根目录新建名为 `secrets.env` 的文件。注意不要保存成 `secrets.env.txt`，文件内容如下：

```dotenv
IMAGE_REF=ghcr.io/xuzihan0823/buff-price-sentinel@sha256:<digest>
LLM_API_KEY=填写你的LLM_API_KEY
QQ_APP_ID=填写你的QQ_APP_ID
QQ_CLIENT_SECRET=填写你的QQ_CLIENT_SECRET
QQ_RECIPIENT_OPENID=填写接收者OPENID
BUFF_SESSION_COOKIE=
BUFF_PROXY_URL=
TZ=Asia/Shanghai
```

完整镜像地址可从最新一次成功的 [GitHub Actions 工作流](https://github.com/xuzihan0823/buff-price-sentinel/actions/workflows/ci.yml)摘要中复制。

### 4. 启动和验证

在项目目录的 PowerShell 中执行：

```powershell
docker compose --env-file secrets.env config
docker compose --env-file secrets.env pull
docker compose --env-file secrets.env up -d --remove-orphans
docker compose --env-file secrets.env ps
```

首次部署后执行一轮安全试采集：

```powershell
docker compose --env-file secrets.env exec -T buff-sentinel buff-sentinel once --config-dir /app/config --dry-run
```

检查健康状态和日志：

```powershell
docker compose --env-file secrets.env exec -T buff-sentinel buff-sentinel healthcheck --config-dir /app/config
docker compose --env-file secrets.env logs --since 20m buff-sentinel
```

测试 QQ 消息发送：

```powershell
docker compose --env-file secrets.env exec -T buff-sentinel buff-sentinel test-notify --config-dir /app/config
```

停止或重新启动服务：

```powershell
docker compose --env-file secrets.env stop
docker compose --env-file secrets.env start
```

移除容器但保留 SQLite 数据卷：

```powershell
docker compose --env-file secrets.env down
```

不要执行 `docker compose down -v`，除非确定要删除全部历史数据。

### Windows 注意事项

- 项目目录建议放在用户目录下，例如 `C:\Users\你的用户名\Documents\buff-price-sentinel`。
- `./config:/app/config:ro` 会由 Docker Desktop 自动映射，无需把容器路径改成 Windows 路径。
- SQLite 数据保存在 Docker 具名卷 `buff-price-sentinel-data` 中，而不是项目目录。
- Windows 防火墙一般不需要开放端口，因为本项目不对外监听 Web 服务端口。
- Intel/AMD Windows 电脑可以直接使用当前 `linux/amd64` 镜像。
- Windows ARM64（例如部分 Snapdragon 电脑）目前没有原生镜像。强制模拟 `linux/amd64` 可能更慢或存在兼容问题，不建议用于长期生产运行。
- Windows Server 需要另行配置 Linux 容器环境；推荐部署到 Linux 服务器，Windows 10/11 Docker Desktop 更适合个人运行和测试。

## 推荐：在本机编辑，然后同步到服务器

不需要在服务器终端里逐个编辑 YAML。推荐在本机使用 VS Code、Cursor 或其他编辑器完成配置，再通过 `rsync` 上传运行文件。

### 1. 本机完成配置

在本机项目目录中准备并编辑：

```text
buff-price-sentinel/
├── docker-compose.yml
├── secrets.env
└── config/
    ├── app.yaml
    ├── items.yaml
    ├── llm.yaml
    └── notifiers.yaml
```

先在本机校验 Compose 配置：

```bash
docker compose --env-file secrets.env config
```

这一步只检查配置，不会启动服务。

### 2. 首次创建服务器目录

将以下示例中的用户名、服务器地址和 SSH 私钥路径换成自己的值：

```bash
ssh -i ~/.ssh/server.pem root@SERVER_IP \
  'install -d -m 700 /root/buff-price-sentinel/config'
```

### 3. 从本机同步到服务器

在本机项目根目录执行：

```bash
rsync -av --progress \
  -e 'ssh -i ~/.ssh/server.pem' \
  docker-compose.yml secrets.env config \
  root@SERVER_IP:/root/buff-price-sentinel/
```

由于命令只上传明确列出的运行文件，因此不会上传源码、Git 历史、缓存或本地数据库。这里刻意不使用 `--delete`，以免误删服务器文件。

上传后修正敏感文件权限并启动：

```bash
ssh -i ~/.ssh/server.pem root@SERVER_IP <<'EOF'
cd /root/buff-price-sentinel
chmod 600 secrets.env
docker compose --env-file secrets.env config
docker compose --env-file secrets.env pull
docker compose --env-file secrets.env up -d --remove-orphans
docker compose --env-file secrets.env ps
EOF
```

以后修改商品或接口配置，只需在本机保存后重新同步并重启：

```bash
rsync -av --progress \
  -e 'ssh -i ~/.ssh/server.pem' \
  secrets.env config \
  root@SERVER_IP:/root/buff-price-sentinel/

ssh -i ~/.ssh/server.pem root@SERVER_IP \
  'cd /root/buff-price-sentinel && docker compose --env-file secrets.env up -d --force-recreate'
```

### 4. 可选：配置 SSH 别名

在本机 `~/.ssh/config` 中加入：

```sshconfig
Host buff-server
    HostName SERVER_IP
    User root
    IdentityFile ~/.ssh/server.pem
```

之后同步命令可以简化为：

```bash
rsync -av --progress docker-compose.yml secrets.env config \
  buff-server:/root/buff-price-sentinel/

ssh buff-server \
  'cd /root/buff-price-sentinel && docker compose --env-file secrets.env up -d --force-recreate'
```

如果不想使用终端同步，也可以使用 VS Code 的 **Remote - SSH** 扩展或支持 SFTP 的图形化客户端，但密钥文件和 `secrets.env` 仍应妥善保护。

## 自动获取 QQ 用户 OpenID

`QQ_RECIPIENT_OPENID` 不能使用 QQ 号代替。项目根目录提供了 `get_qq_openid.py`：它会连接 QQ 机器人事件网关，等待目标用户给机器人发送一条单聊消息，然后读取 `author.user_openid`，自动写入本机的 `secrets.env` 后退出。

目标 QQ 必须已加入机器人的沙箱单聊名单，或者机器人已经正式上线并向该用户开放。

macOS 或 Linux：

```bash
python3 -m venv .qq-openid-venv
.qq-openid-venv/bin/pip install qq-botpy
.qq-openid-venv/bin/python get_qq_openid.py
```

Windows PowerShell：

```powershell
py -m venv .qq-openid-venv
.\.qq-openid-venv\Scripts\python.exe -m pip install qq-botpy
.\.qq-openid-venv\Scripts\python.exe .\get_qq_openid.py
```

脚本会优先读取 `secrets.env` 中已有的 `QQ_APP_ID` 和 `QQ_CLIENT_SECRET`；如果缺少，会提示输入并保存。输入 `Client Secret` 时不会回显内容。看到等待提示后，使用需要接收提醒的 QQ 给机器人发送任意一条单聊消息。成功后会显示：

```text
QQ_RECIPIENT_OPENID=获取到的用户OpenID
已自动写入：项目目录/secrets.env
```

`secrets.env` 已被 Git 忽略。不要将机器人密钥或用户 OpenID 提交到仓库。

## 配置说明

项目提供以下 4 个示例配置文件：

| 文件 | 用途 |
| --- | --- |
| `config/app.example.yaml` | 时区、SQLite URL、采集周期、BUFF 请求行为和提醒冷却时间 |
| `config/items.example.yaml` | 已持有和愿望单商品及其阈值 |
| `config/llm.example.yaml` | 兼容 OpenAI 的基础 URL、模型、重试和失败降级行为 |
| `config/notifiers.example.yaml` | QQ 机器人接口地址、凭据、接收者和重试行为 |

环境变量引用格式为 `${NAME}` 或 `${NAME:-default}`。缺少必需的环境变量或配置无效时，程序会拒绝启动。

容器中的 `database_url` 应使用：

```text
sqlite:////app/data/buff-sentinel.db
```

应用数据保存在名为 `buff-price-sentinel-data` 的 Docker 卷中，重新创建容器不会清除历史数据。

已持有商品支持：

- `profit_pct`：盈利比例提醒
- `loss_pct`：亏损比例提醒
- `alert_above_price`：最低卖价从阈值下方向上突破时提醒；持续高于阈值不会重复触发

愿望单商品支持：

- `target_price`：最低卖价低于或等于目标价时提醒
- `drop_pct_24h`：24 小时跌幅达到阈值时提醒
- `rise_pct_24h`：24 小时涨幅达到阈值时提醒

## 命令行工具

```text
buff-sentinel run              # 启动守护进程（默认每 10 分钟执行一次）
buff-sentinel once             # 执行一轮采集
buff-sentinel validate-config  # 加载并汇总配置
buff-sentinel test-notify      # 发送一条 QQ 机器人测试消息
buff-sentinel healthcheck      # 检查配置、数据库和近期快照
```

所有命令均支持 `--config-dir <目录>`。`once --dry-run` 会获取 BUFF 报价、写入快照并评估规则，但会跳过 LLM 调用、QQ 消息发送和提醒去重记录写入。

## 本地开发

本地开发需要 Python 3.12：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

export LLM_API_KEY=...
export QQ_APP_ID=...
export QQ_CLIENT_SECRET=...
export QQ_RECIPIENT_OPENID=...

buff-sentinel validate-config --config-dir config
buff-sentinel once --config-dir config --dry-run
buff-sentinel run --config-dir config
```

运行质量检查：

```bash
ruff check src tests
mypy src
pytest
docker build --tag buff-price-sentinel:local .
```

GitHub Actions 会在发布主分支镜像到 GHCR 前运行相同的检查。生产部署必须使用工作流报告的不可变 digest，不应使用 `latest` 作为生产版本或回滚目标。

## 备份与回滚

替换服务器上的现有部署前，应备份 `/root/buff-price-sentinel` 和 SQLite 数据。部署元数据可以记录在仅 root 可写的 `RELEASE` 文件中，其中包含提交版本、镜像 digest、部署时间和备份文件名。

如需回滚，请将 `secrets.env` 中的 `IMAGE_REF` 改为上一个成功版本的 digest，然后执行：

```bash
docker compose --env-file secrets.env pull
docker compose --env-file secrets.env up -d --remove-orphans
```

## 设计概要

有关 `config`、`buff`、`storage`、`analytics`、`llm`、`notifier`、`service` 和 `cli` 各分层边界的说明，请参阅 `.trellis/tasks/07-14-buff-price-sentinel/design.md`。

## 许可证

MIT。
