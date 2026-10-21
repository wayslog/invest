# Linux 每日运行与迁移

运行包版本 0.6.1。systemd 配置在 [deploy](../deploy/)，
本地配置示例为 [operations.toml](../configs/operations.toml)。
部署是否已启动，以 [M3 阶段记录](milestones/m3.md) 和目标主机的验收凭据为准。
代码和部署包准备完成本身不代表定时器已经在主机运行。
GitHub Actions 可执行连接预检与受控部署，配置及账户交接见
[Actions 部署说明](github-actions-deployment.md)。每日任务仍在持久主机运行。

0.6.1 修复日结和健康 CLI 对时间字段的 JSON 输出。0.6.0 的主机日结曾已成功提交、
对账及备份，却在输出阶段报错退出；已有成功凭据和第一个交易日继续有效。
修复也会改变引擎源码指纹，必须使用显式迁移，不能只替换代码或清空账户。
2026-10-21 北京时间 **19:15:43**，[0.6.1 主机发布](https://github.com/wayslog/invest/actions/runs/39589686259)
完成；原账户保留 1/60 日记录，两个 timer 均 enabled/active。首轮故障与告警凭据保留。
主机 `/var/lib/invest/account` 是唯一权威写入端，云工作区的原账户目录只作停止更新的存档。

## 账户版本迁移

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
| `/var/lib/invest/account` | 从原位置移交的同一账户及全部日志 |
| `/var/lib/invest/data` | 原始行情、发行方证据及失败批次 |
| `/var/lib/invest/backups/<账户ID>/<head>` | 每个已核对 head 的不可覆盖备份 |
| `/var/lib/invest/operations` | 运行凭据、看门狗检查、告警及交付结果，均为 Parquet/Zstandard |
| `/etc/invest/operations.toml` | root:invest、0640；运行路径和通知配置 |
| `/etc/invest/invest.env` | root:root、0600；由 systemd 安全注入凭据 |

服务使用无交互登录权限的 `invest` 用户，代码与系统目录只读，只有持久化目录允许写入。
SSH 地址和实际凭据保存在本地忽略的部署记录/安全环境中，不写入公开仓库。
Actions 首次连接时自动记录主机密钥，无需单独配置 known_hosts。
私钥变量为 `INVEST_SSH_PRIVATE_KEY` 或 `INVEST_SSH_KEY_FILE`；连接时不转发 SSH agent。

## 凭据与 Telegram

服务器的受保护 EnvironmentFile 需要：

```text
APCA_API_KEY_ID=安全配置的行情Key
APCA_API_SECRET_KEY=安全配置的行情Secret
INVEST_TELEGRAM_BOT_TOKEN=安全配置的BotToken
INVEST_TELEGRAM_ALLOWED_UID=唯一允许接收通知的正整数用户ID
```

allowed UID 只作为固定收件人，不支持群组 ID，不接受聊天传入的账户或交易指令。
Bot 为单向通知，不监听命令或开放远程交易入口。收件人须先在 Telegram 中启动该 Bot。
发送采用 HTTPS，禁止重定向；成功必须收到同一 UID 的 API 回执。
HTTP 错误和网络错误不会把含 Token 的请求 URL 或响应正文写入日志。

同一告警默认六小时去重；恢复后发送恢复通知。部署自检不被去重，必须得到新回执。
Python 能捕获的错误会保存运行失败记录并通知；systemd 的超时/进程异常通过独立
`OnFailure` 单元通知。Telegram 失败自身也会记录，不伪装为消息已经送达。

## 安装与首次验收

先检查主机架构、磁盘、Python 3.12、uv、systemd、NTP 和访问行情/发行方/Telegram 的网络。
安装 Python 时应放在系统目录或 `/opt/invest/python`，不能让服务依赖 `/root` 下的解释器。
在版本目录运行 `uv sync --locked --no-dev --python 3.12`。

迁移后的账户先停止源端写入，再按原字节移交。目标账户目录必须不存在；
解包到暂存目录，核对传输清单、相同 head、账户 ID 与新引擎复核后再发布。
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
  XNYS 日历和供应方纽约次日 00:15 截点决定是否有新会话；时区和夏令时由引擎处理。
- 每次调用先复核旧状态，再捕获发行方/行情，随后逐事件重放及独立对账，最后备份。
  即使 `due=false`，也会检查当前 head 并留下持久化心跳。
- 同一服务锁覆盖整次运行；账户锁和 head 比较继续防止人工控制或其他任务覆盖。
- 独立看门狗每十五分钟检查心跳、当前引擎/head 与备份；超过 150 分钟无完成记录即告警。
- `Persistent=true` 会在主机恢复后补执行任务；多会话缺口仍由引擎记录为漏跑、只补已有义务，
  不能补造过去的交易决定。冻结窗口及覆盖判据不因重启或迁移改变。

```bash
systemctl list-timers invest-forward.timer invest-forward-health.timer
journalctl -u invest-forward.service -u invest-forward-health.service -n 100
/opt/invest/current/.venv/bin/invest forward-status --account /var/lib/invest/account
```

本机备份可用于应用恢复；整机或磁盘故障还需要异机/独立存储副本。
主机整体离线时本机看门狗也会离线，须另接外部主机可用性监控，不能将本机 timer 当作外部监控。
当前没有配置外部存储或外部监控时，应在部署验收记录中明确保留这两个边界。

观察结束后先核对 `operations=completed`、无持仓/应收/待处理意图及原窗口覆盖结果，
再停用两个 timer，完成最终备份和归档。该实验的定时运行结束，不再要求采集窗口以外的会话；
下一项实验或新策略不能通过重建此资金账户来清空风险历史。
