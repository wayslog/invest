# Linux 每日运行与迁移

当前实现及部署版本 0.7.1；旧账户最后验收版本为 0.6.1。systemd 配置在 [deploy](../deploy/)，
本地配置示例为 [operations.toml](../configs/operations.toml)。
部署是否已启动，以 [M3 阶段记录](milestones/m3.md) 和目标主机的验收凭据为准。
代码和部署包准备完成本身不代表定时器已经在主机运行。
GitHub Actions 可执行连接预检与受控部署，配置及账户交接见
[Actions 部署说明](github-actions-deployment.md)。每日任务仍在持久主机运行。

2026-10-23 用户明确要求不修订已暂停旧账户的数据，直接从零开始。新的
[IBKR 现金观察](ibkr-cash-observation.md)使用 `backend="ibkr_cash"`，仅采集 IBKR 只读数据，
并使用独立的 5,000 美元虚拟现金账户和新 60 日窗口；旧 2/60 账户与运维记录归档。
本次切换通过 Actions `operation=restart` 完成，实际主机验收状态以阶段记录为准。
2026-10-23 17:23（北京时间）核查已通过：新账户 0/60、来源 ibkr、运行 active，
对账、本机备份、Telegram 和两个 timer 正常；窗口为 2026-10-23 至 2027-01-20。
以下保留旧 `legacy_forward` 的迁移说明，不能用它初始化新的 IBKR 观察。

0.6.1 修复日结和健康 CLI 对时间字段的 JSON 输出。0.6.0 的主机日结曾已成功提交、
对账及备份，却在输出阶段报错退出；已有成功凭据和第一个交易日继续有效。
修复也会改变引擎源码指纹，必须使用显式迁移，不能只替换代码或清空账户。
2026-10-21 北京时间 **19:15:43**，[0.6.1 主机发布](https://github.com/wayslog/invest/actions/runs/39589686259)
完成；原账户保留 1/60 日记录，两个 timer 均 enabled/active。首轮故障与告警凭据保留。
主机 `/var/lib/invest/account` 是唯一权威写入端，云工作区的原账户目录只作停止更新的存档。

## 旧账户版本迁移

`forward-migrate` 仅支持 `cash_observation` 和明确合成的 `drill`。
迁移前停止同一逻辑账户的其他写入进程，保留外部保存的原 head 和原引擎指纹。

```bash
uv run --locked invest forward-migrate \
  --account reports/m3-cash-account \
  --expected-head 原日志head --from-engine 原引擎SHA256 \
  --backup reports/backups/迁移前唯一目录 \
  --actor owner --reason "旧引擎复核通过，接续已验收的运行版本"
uv run --locked invest forward-verify --account reports/m3-cash-account
```

程序先核对 head、身份和版本，再把旧日志前缀复制到临时目录，用归档的旧源码完整重放。
旧代码子进程不接收市场 API、SSH 或 Telegram 凭据；使用当前锁定的 Python/依赖运行。
若归档版本与当前依赖不兼容，迁移会拒绝，不能跳过复核。
复核成功后创建不可覆盖的迁移前备份，并追加一条 `migrate` 日志。

迁移不修改旧登记或旧日志。新事件保存原 head、双方引擎指纹、版本、操作人、原因、
旧引擎复核凭据、新源码和依赖清单。现金、高点、风险锁、已核算会话、持仓、应收及
全部待处理意图必须逐表等值；运行状态变为 paused，已完成/停止账户保持原状态。
迁移本身不取消原意图，不补造原始信号，不延长观察窗口。

提交是原子目录重命名。提交前崩溃不改变原账户；同一迁移的提交后重试不会重复追加。
后续复核按版本边界用各自归档引擎验证历史，再由当前引擎重建当前区间；
不能用新规则追改旧版本的决策。没有迁移事件的指纹变化仍然拒绝。
策略账户涉及重新验证资格，本版不允许把旧资格直接迁移到新引擎。

完成核对及有效数据补账后，才显式恢复运行：

```bash
uv run --locked invest forward-control --account reports/m3-cash-account \
  --action resume --actor owner --reason "迁移、资金与风险状态复核完成"
```

恢复不会清除风险锁；若已漏过会话，先补齐已有义务与估值，原窗口的漏跑仍保留。

## 目标主机与目录

默认使用一台持续运行且时钟同步的 Linux/systemd 主机：

| 路径 | 用途与权限 |
| --- | --- |
| `/opt/invest/releases/<Git提交>` | 经验证的不可变源码包和 Python 3.12 环境；代码由 root 管理 |
| `/opt/invest/current` | 指向当前已验收版本的符号链接 |
| `/var/lib/invest/account` | 当前唯一活动观察账户；本次切换后为新 IBKR 现金观察 |
| `/var/lib/invest/data` | 每次采集的原始与规范化数据及失败批次；历史来源仍明确保留 |
| `/var/lib/invest/archives/m3-ibkr-cash-v1` | 本次重开前的旧账户、operations 和运行配置；不改写旧日志 |
| `/var/lib/invest/restarts/m3-ibkr-cash-v1` | 本次重开的固定请求与进度，重试续接同一新账户 |
| `/var/lib/invest/backups/<账户ID>/<head>` | 每个已核对 head 的不可覆盖备份 |
| `/var/lib/invest/operations` | 运行凭据、看门狗检查、告警及交付结果，均为 Parquet/Zstandard |
| `/etc/invest/operations.toml` | root:invest、0640；运行路径和通知配置 |
| `/etc/invest/invest.env` | root:root、0600；由 systemd 安全注入凭据 |

服务使用无交互登录权限的 `invest` 用户，代码与系统目录只读，只有持久化目录允许写入。
SSH 地址和实际凭据保存在本地忽略的部署记录/安全环境中，不写入公开仓库。
完全信任已配置的主机；Actions 不检查或保存主机指纹，无需 known_hosts。
私钥变量为 `INVEST_SSH_PRIVATE_KEY` 或 `INVEST_SSH_KEY_FILE`；连接时不转发 SSH agent。

## 凭据与 Telegram

服务器的受保护 EnvironmentFile 为新观察提供通知凭据；IBKR 通过主机已登录 Gateway 的
`127.0.0.1:4002` 接入，不把 IBKR 登录密码传给日结服务：

```text
INVEST_TELEGRAM_BOT_TOKEN=安全配置的BotToken
INVEST_TELEGRAM_ALLOWED_UID=唯一允许接收通知的正整数用户ID
```

旧 `APCA_API_KEY_ID`、`APCA_API_SECRET_KEY` 只供旧 Alpaca 流程使用，新 IBKR 观察不依赖它们。

allowed UID 只作为固定收件人，不支持群组 ID，不接受聊天传入的账户或交易指令。
Bot 为单向通知，不监听命令或开放远程交易入口。收件人须先在 Telegram 中启动该 Bot。
发送采用 HTTPS，禁止重定向；成功必须收到同一 UID 的 API 回执。
HTTP 错误和网络错误不会把含 Token 的请求 URL 或响应正文写入日志。

本机同一告警默认六小时去重；恢复后发送恢复通知。部署自检不被去重，必须得到新回执。
Python 能捕获的错误会保存运行失败记录并通知；systemd 的超时/进程异常通过独立
`OnFailure` 单元通知。Telegram 失败自身也会记录，不伪装为消息已经送达。

## 本次从零重开与验收

从 `main` 触发 Actions **Deploy to Linux** 的 `operation=restart`，无需填写账户 ID、
head、摘要或额外确认字段。它安装测试通过的核心环境与隔离 SDK，先成功预采集并登记候选观察，
再停止旧 writer、归档旧账户/operations/配置、切换到新的标准目录。
Telegram 自检、首个服务心跳、核对、本机备份和健康检查全部通过后才启用两个 timer。
初始化和预采集不算观察日，新账户从 0/60 开始。

固定请求名为 `m3-ibkr-cash-v1`；重试续接同一新账户，不重复清零。切换前失败保留原账户；
账户切换后失败保留新旧文件并停用 timer，待同一次重开续跑，不能自动回滚或再次开户。
通过 `operation=inspect` 查询新观察状态；`forward-status`、`forward-verify`、
`forward-backup` 和 `forward-job` 也会识别新观察格式。新观察不使用旧 `forward-control/migrate/run`。

## 旧 forward 账户安装与首次验收

先检查主机架构、磁盘、Python 3.12、uv、systemd、NTP 和访问行情/发行方/Telegram 的网络。
安装 Python 时应放在系统目录或 `/opt/invest/python`，不能让服务依赖 `/root` 下的解释器。
在版本目录运行 `uv sync --locked --no-dev --python 3.12`。

迁移后的账户先停止源端写入，再按原字节移交。目标账户目录必须不存在；
通过 SSH 直接复制归档并解包到暂存目录；沿用同一账户与历史，无需签名证书或传输摘要。
不能覆盖服务器已有账户，也不能同时启用云工作区与服务器两份写入进程。
首次交接记录须保存权威主机、路径、源/目标 head 和校验结果。

准备好同一账户、锁定环境和受保护凭据后，在主机执行：

```bash
bash /opt/invest/releases/实际版本/deploy/install-systemd.sh \
  /opt/invest/releases/实际版本
```

安装器先拒绝已有活动 writer，验证 NTP、运行用户、目录权限和账户重放，再安装单元。
只有 Telegram 自检、首次任务及看门狗均通过后才启用两个定时器。
升级已有部署须先停 writer、备份及执行版本迁移，不直接重新指向新源码。

## 调度、日结与漏跑

- 主任务每个 UTC 小时的 `:17` 执行，允许最多 30 秒随机延迟。
  新 IBKR 观察在 XNYS 每日收盘后 60 分钟开始采集，下一交易日开盘为及时观察截止；
  半日市、节假日和夏令时由交易所日历处理。旧 Alpaca 观察的截点仍保留为历史口径。
- 新观察只核查当次 IBKR 账户与行情回执及固定虚拟现金，不比较历史前缀或修订旧日结。
  每次调用会核对账户、保存本机备份和持久化心跳，`due=false` 也不例外。
- 同一服务锁覆盖整次运行；账户锁和 head 比较继续防止人工控制或其他任务覆盖。
- 独立看门狗每十五分钟检查心跳、当前引擎/head 与备份；超过 150 分钟无完成记录即告警。
- `Persistent=true` 会在主机恢复后补执行任务；新观察允许窗口内失败重试。错过下一开盘的会话
  永久记为 `missed`，不补成及时观察；历史漏跑与当前待处理会话分开报告。
  已登记的新 60 日窗口不因重启、漏跑或后续部署延长。

```bash
systemctl list-timers invest-forward.timer invest-forward-health.timer
journalctl -u invest-forward.service -u invest-forward-health.service -n 100
/opt/invest/current/.venv/bin/invest forward-status --account /var/lib/invest/account
/opt/invest/current/.venv/bin/invest forward-verify --account /var/lib/invest/account
```

观察状态从 Actions `operation=inspect` 查询，它根据已部署后端读取当前账户。
按用户决定仅保留本机备份，不引入外部备份存储或相关配置。
主机外的运行检查由 [M3 runtime observation](../.github/workflows/monitor.yml) 执行，
复用现有 SSH 和 Telegram 凭据，每小时 `:43` 从 GitHub runner 查询主机状态。
它读取账户、日结、健康记录、定时器和本机备份状态，不执行行情采集或日结。

在 Actions 的 **M3 runtime observation → Summary** 查看运行日报：实际观察天数、
最新核算交易日、下次采集时间、日结心跳、本机备份及过去 24 小时的异常计数。
时间按北京时间显示，运行状态表使用带类型的 Parquet/Zstandard，作为该次作业的 artifact 保存 90 天。
表中只有运行状态和观察计数；账户账本、资金、持仓和凭据保存在主机。

主机连接失败、日结心跳过期、账户对账失败、定时器停用或本机备份未接续时，
由 runner 向既有 Telegram 收件人告警，异常持续时随每小时检查提醒；之后一次正常检查会发送恢复通知。
定时检查正常时不发送通知，手动触发会发送一次通道自检。
GitHub 调度可能延迟，报告保留真实采样时间，不用于补记交易日观察。
每天的可采集时间之前保持原天数属于正常状态；可采集时间后的 20 分钟用于等待本机任务完成。

观察结束后先核对 `operations=completed`、无持仓/应收/待处理意图及原窗口覆盖结果，
再停用两个 timer，完成最终备份和归档。该实验的定时运行结束，不再要求采集窗口以外的会话；
运行日报显示窗口已结束，不将窗口后的行情提示为实验待处理任务。
本次用户授权的新观察独立于旧账户；后续实验、升级或策略变更仍不能自动重建当前账户来清空风险历史。
