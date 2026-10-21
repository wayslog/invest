# GitHub Actions 部署

Actions 负责连接预检、测试、构建和发布；持久 Linux 主机继续通过 systemd 执行每日任务。
账户、行情、备份和运行凭据留在 `/var/lib/invest`。不把每日账户写入任务放到临时 runner，
也不以 GitHub 定时触发的时间代替真实观察时间。

工作流为 [deploy.yml](../.github/workflows/deploy.yml)，只允许从 `main` 手动触发，
同一时间只执行一次生产部署。构建复用 [CI](../.github/workflows/ci.yml)，只有
静态检查、完整测试、两个离线演示和打包全部通过，才会进入持有生产凭据的部署 job。
当前文件实现完成不表示 workflow 已推送、secrets 已配置或主机已上线。

## GitHub 配置

在仓库 Settings → Environments 创建 `production`，部署分支限制为 `main`。
在该 Environment 配置以下 secrets，不在聊天、workflow 输入、Git 或公开日志粘贴值。
当前 Codex GitHub 集成访问 Actions 配置/secrets 返回 403，不能代替仓库管理员配置它们。
云工作区里已有的 Alpaca 环境变量不会自动同步成 GitHub secrets。
账户 ID、日志 head 和账户包校验值由程序自动读取，不需要配置账户元数据。

| Secret | 用途 |
| --- | --- |
| `INVEST_SSH_HOST` | 主机地址 |
| `INVEST_SSH_PRIVATE_KEY` | 供 runner 使用的独立、无交互解密的 SSH 私钥 |
| `APCA_API_KEY_ID`、`APCA_API_SECRET_KEY` | 行情读取凭据 |
| `INVEST_TELEGRAM_BOT_TOKEN`、`INVEST_TELEGRAM_ALLOWED_UID` | 通知凭据及唯一私人收件人 UID |

Environment variables 可选 `INVEST_SSH_USER=root`、`INVEST_SSH_PORT=22`。
当前安装器需要 root；常驻账户服务使用独立的 `invest` 用户。
主机密钥由 SSH 首次连接时自动记录，无需配置 known_hosts。
同一作业的预检、传输和部署共用该记录；后续连接的密钥若变化会拒绝。
GitHub 托管 runner 每次创建新作业记录，不在作业间保存主机密钥，也不转发 SSH agent。

目标机须运行 systemd，具备同步时钟、uv 和常见系统工具，允许下载锁定依赖、Python、
行情及访问 Telegram。uv 使用 `/opt/invest/python` 安装 Python 3.12，避免依赖 root HOME。
预检明确拒绝缺少这些条件的主机，不修改账户、服务、目录或凭据。

## 首次交接原账户

服务器已有 `/var/lib/invest/account` 时，部署直接使用该账户，不需要账户包。
服务器首次接手时，自动读取固定路径 `/opt/invest/bootstrap/account.tar.gz`，
或本地部署器随 SSH 传输的账户包。无需对象存储、下载 URL、手填账户 ID 或摘要。

源端停止写入后，用下面的命令导出当前账户；身份和日志校验自动完成：

```bash
uv run --locked python deploy/release.py pack-account \
  reports/m3-cash-account reports/deployments/account.tar.gz
```

一次性把该包通过可信 SSH 连接放到服务器固定路径，目录 0700、文件 0600、root 持有。
已有本地账户的部署器也会自动打包并传输；自定义目录可用可选的 `--account` 参数指定。
GitHub 托管 runner 无法读取云工作区里未提交的私人文件，因此首次仍需实际移交数据；
账户包由部署者准备，不作为额外 GitHub secret，不上传公开 artifact。

程序完整重放账户日志并自动取得 ID/head；已有账户不会被包覆盖，也不会重新开户。
首次交接后，Linux 主机成为唯一写入端，本地副本留作停止更新的存档。

## 执行与验收

在 Actions → **Deploy to Linux** → Run workflow：

1. 选择 `main`、`operation=preflight`，检查 GitHub runner 的 SSH 连通性、
   root 权限、systemd、NTP 和 uv。预检成功只证明接入前提成立，不代表日结已部署。
2. 选择 `operation=deploy`。没有账户元数据输入或首次交接确认框。
3. 测试通过后，部署脚本核对构建包 SHA，在 `/opt/invest/releases/<完整Git提交>` 安装锁定环境。
   同一个引擎可以有多个不同部署版本；发布身份使用 Git commit，避免脚本更新与引擎指纹混淆。
4. 停止两个 timer，等待已有服务自然结束，再自动读取服务器账户的最新 ID/head，验证日志并备份。
   等待期间正常完成的日结无需人工处理。部署内部继续核对后续 head，拒绝并发替换账户、
   损坏日志、暂停状态或引擎不匹配。
5. 安装配置后依次运行 Telegram 自检、首次日结和健康检查，均通过后保存私有
   Parquet/Zstandard 部署凭据，最后启用两个 timer。日结按真实时间记录，漏跑不会追认为及时观察。

成功凭据在 `/var/lib/invest/operations/deployments/<run-id>-<attempt>.parquet`，
记录 Git commit、源码/引擎 SHA、账户 ID、交接 head、首轮日结后 head 和权威路径。
这些私人数据不进入 Actions 日志或 artifacts。Actions 只上传经过测试的公开源码包。

## 失败与升级

GitHub runner 同样可能被目标机网络或防火墙拒绝；Actions 迁移不能保证解决 SSH 拒绝连接。
预检失败时先检查安全组、sshd 和出口限制。若主机只允许内网接入，
可在受信任的持久主机设置专用 runner；生产 runner 只运行受保护部署任务，不接收 PR 代码。

激活前失败会恢复此前活动的 timer。激活后失败会停用 timer、保留当前账户与发布状态，
不自动回滚源码、资金或日志；首次日结可能已提交新事件，须按新 head 处理。
受保护失败日志在 `/opt/invest/deployment-logs/<run-id>-<attempt>/`，服务日志在 journalctl。
runner/主机私有暂存包在作业结束时清理；若 SSH 中断导致清理失败，检查
`/opt/invest/incoming/` 并清理遗留文件。

目前自动发布仅支持**账户引擎指纹不变**的部署调整。代码改变引擎后先按
[账户迁移说明](operations.md) 在唯一权威主机上完成显式迁移、复核及人工恢复；
再直接发布；当前 head 自动读取。workflow 不自动迁移、恢复运行层或清除风险状态。
未完成首次交接前，本地账户仍是权威来源，不能把一个绿色构建当成运行已上线。

本机备份和本机健康 timer 的边界仍见运行说明；独立存储备份和整机可用性监控
需要另外接入，GitHub 部署成功不代表这两项已经配置。
