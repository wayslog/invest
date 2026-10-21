# GitHub Actions 部署

Actions 负责连接预检、测试、构建和发布；持久 Linux 主机继续通过 systemd 执行每日任务。
账户、行情、备份和运行凭据留在 `/var/lib/invest`。不把每日账户写入任务放到临时 runner，
也不以 GitHub 定时触发的时间代替真实观察时间。

工作流为 [deploy.yml](../.github/workflows/deploy.yml)，只允许从 `main` 手动触发，
同一时间只执行一次生产部署。构建复用 [CI](../.github/workflows/ci.yml)，只有
静态检查、完整测试、两个离线演示和打包全部通过，才会进入持有生产凭据的部署 job。
截至 2026-10-21，工作流已推送；提交 `8de63b8` 的
[CI](https://github.com/wayslog/invest/actions/runs/39581499422)和
[SSH/主机只读预检](https://github.com/wayslog/invest/actions/runs/39582930230)通过。
预检运行的 `build`/`deploy` job 均跳过。
首次[正式发布试跑](https://github.com/wayslog/invest/actions/runs/39583795728)的完整测试、
构建和主机锁定环境安装通过，但在 `verify_bootstrap` 阶段因原账户尚未移交而停止；
未启动账户服务或定时器。
后续[主机验收](https://github.com/wayslog/invest/actions/runs/39587121916)已完成原账户交接、
Telegram 自检/故障通知、首个交易日采集、12 项对账及备份；日结提交后，0.6.0 CLI
因时间字段无法输出 JSON 而退出失败。该次账户仍保持 active，已有 1/60 日，定时器保持禁用。
0.6.1 随后修复 CLI，并于北京时间 **19:15:43** 完成
[显式迁移及正式发布](https://github.com/wayslog/invest/actions/runs/39589686259)。
原账户、资金、高点、风险和全部旧日志保留，仍为 1/60 日，两个 timer 均 enabled/active。
日结、备份、Telegram、健康检查以及 36 项私人凭据核对通过；
[同提交 CI](https://github.com/wayslog/invest/actions/runs/39589626803)为 254 项测试、88% 覆盖率。
正式版本为 [v0.6.1](https://github.com/wayslog/invest/releases/tag/v0.6.1)，代码提交 `f468424`。
首次 CLI 失败及故障通知继续保留，不因最终发布成功而抹去。

## GitHub 配置

仓库已存在 `production` Environment，workflow 要求从 `main` 执行。
该 Environment 使用以下 secrets，不在聊天、workflow 输入、Git 或公开日志粘贴值。
当前 Codex GitHub 集成读取 production secrets 列表返回 403，不能完整核实或管理凭据清单。
SSH、行情读取和 Telegram 的实际送达已经验证；凭据清单 API 权限不影响这些运行证据。
云工作区里已有的 Alpaca 环境变量不会自动同步成 GitHub secrets。
账户 ID 和日志 head 由程序自动读取，不需要配置账户元数据、签名证书或传输摘要。

| Secret | 用途 |
| --- | --- |
| `INVEST_SSH_HOST` | 主机地址 |
| `INVEST_SSH_PRIVATE_KEY` | 供 runner 使用的独立、无交互解密的 SSH 私钥 |
| `APCA_API_KEY_ID`、`APCA_API_SECRET_KEY` | 行情读取凭据 |
| `INVEST_TELEGRAM_BOT_TOKEN`、`INVEST_TELEGRAM_ALLOWED_UID` | 通知凭据及唯一私人收件人 UID |

Environment variables 可选 `INVEST_SSH_USER=root`、`INVEST_SSH_PORT=22`。
当前安装器需要 root；常驻账户服务使用独立的 `invest` 用户。
按用户要求完全信任此主机，SSH 不检查或保存主机指纹；无需 known_hosts 配置。
部署通过现有 SSH 私钥连接，不转发 SSH agent。账户包不再签名、加密封装或另行核对传输摘要。

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
本地部署器可用 `--account` 指定待交接的账户，直接通过 SSH 打包传输。
GitHub 托管 runner 无法读取云工作区里未提交的私人文件，因此首次仍需实际移交数据；
账户包不作为额外 GitHub secret，不上传公开 artifact。

当前原账户已完成交接。日常 Actions 部署直接沿用主机账户，不再经过 Git blob、
临时密钥、证书或签名流程，也不需要上传账户包。首次移交其他主机时，通过 SSH 复制上述归档即可。

程序完整重放账户日志并自动取得 ID/head；已有账户不会被包覆盖，也不会重新开户。
首次交接后，Linux 主机成为唯一写入端，本地副本留作停止更新的存档。

## 执行与验收

在 Actions → **Deploy to Linux** → Run workflow：

1. 选择 `main`、`operation=preflight`，检查 GitHub runner 的 SSH 连通性、
   root 权限、systemd、NTP 和 uv。预检成功只证明接入前提成立，不代表日结已部署。
2. 选择 `operation=deploy`。没有账户元数据输入或首次交接确认框。
3. 测试通过后，部署脚本直接使用构建 job 的源码包，在 `/opt/invest/releases/<完整Git提交>` 安装锁定环境。
   同一个引擎可以有多个不同部署版本；发布身份使用 Git commit，避免脚本更新与引擎指纹混淆。
4. 停止两个 timer，等待已有服务自然结束，再自动读取服务器账户的最新 ID/head，验证日志并备份。
   等待期间正常完成的日结无需人工处理。部署内部继续核对后续 head，拒绝并发替换账户、
   损坏日志、暂停状态或引擎不匹配。
5. 安装配置后依次运行 Telegram 自检、首次日结和健康检查，均通过后保存私有
   Parquet/Zstandard 部署凭据，最后启用两个 timer。日结按真实时间记录，漏跑不会追认为及时观察。

成功凭据在 `/var/lib/invest/operations/deployments/<run-id>-<attempt>.parquet`，
记录 Git commit、源码/引擎 SHA、账户 ID、交接 head、首轮日结后 head 和权威路径。
源码 SHA 仅作自动记录，不作为部署门禁；账户引擎绑定和资金对账继续按原逻辑运行。
这些私人数据不进入 Actions 日志或 artifacts。Actions 只上传经过测试的公开源码包。

## 失败与升级

GitHub runner 同样可能被目标机网络或防火墙拒绝；Actions 迁移不能保证解决 SSH 拒绝连接。
预检失败时先检查安全组、sshd 和出口限制。若主机只允许内网接入，
可在受信任的持久主机设置专用 runner；生产 runner 只运行受保护部署任务，不接收 PR 代码。

普通部署在激活前失败会恢复此前活动的 timer。进入显式迁移或激活后失败会停用 timer、保留当前账户与发布状态，
不自动回滚源码、资金或日志；首次日结可能已提交新事件，须按新 head 处理。
受保护失败日志在 `/opt/invest/deployment-logs/<run-id>-<attempt>/`，服务日志在 journalctl。
runner/主机私有暂存包在作业结束时清理；若 SSH 中断导致清理失败，检查
`/opt/invest/incoming/` 并清理遗留文件。

从 `main` 执行 `operation=inspect` 即可查看服务、定时器、账户运行状态及最新运行/告警摘要，
不需要证书、额外输入或下载解密。原始账户、完整日志及 Parquet 记录继续保存在主机，
Actions 仅显示运行摘要。此操作只读账户，不运行日结或修改定时器。

普通 `operation=deploy` 只接受**账户引擎指纹不变**的更新，仍拒绝版本不匹配或暂停账户。
明确需要切换引擎时，可选择 `operation=migrate` 并填写 `migration_reason`，不需要额外 secret
或手填账户 ID/head。该操作仍先完整测试构建，只支持已经交接到主机、账务最新、运行和风险均
active 的现金观察账户；策略账户、已暂停/停止、漏账或风险停用账户均拒绝。

迁移先停止 timer 并等待 writer 结束，再读取实时 head，用归档源码完整重放原日志，创建唯一
迁移前备份，调用[既有迁移流程](operations.md)追加迁移事件。actor 记录为 GitHub 发起人。
新引擎重放通过后显式追加 resume，并逐表核对资金、高点、风险、义务和旧日志保持等值；
再完成 Telegram、日结、健康检查和部署凭据。已完成交易日不会重新计数，登记窗口不改变。
迁移开始后失败会保持 timer 关闭，不重启旧引擎，也不自动回滚资金或日志。
若迁移已提交而恢复未完成，按迁移记录核查后手动继续，不能把一般暂停当作部署可自动恢复。
未完成首次交接前，本地账户仍是权威来源；完成交接后，主机为唯一写入端。

本机备份和本机健康 timer 的边界仍见运行说明；独立存储备份和整机可用性监控
需要另外接入，GitHub 部署成功不代表这两项已经配置。
