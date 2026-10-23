# 无桌面 VPS 上安装 IB Gateway

核查日期：2026-10-23（北京时间）。用户已完成 VPS Gateway 配置，Paper API 会话检查通过。
以下保留官方安装参考和我们建议的虚拟图形方案，不表示已核查用户采用的具体安装方式。

## 安装在哪里

推荐在现有持续运行的 Linux VPS 上安装 **IB Gateway Stable**，项目的 Python 适配器也在
同一主机运行。TWS 和 Gateway 二选一即可，不需要两个都安装。Gateway 省去了完整的
交易工作台，适合我们的后台采集及 Paper 执行服务。

也可以先在个人电脑安装 Gateway 或 TWS 做连接试验，但电脑关机或休眠就会中断会话。
GitHub Actions 负责部署和检查，不承载长期登录的 Gateway 进程。

连接关系为：`Python → 127.0.0.1:4002 → IB Gateway → IBKR Paper`。
安装 Python SDK 不会自动安装 Gateway，也不能代替 Gateway 登录。

## VPS 没有 GUI 能否运行

可以，但需要给 Gateway 提供图形环境。官方明确说 Gateway/TWS 登录窗口需要手动输入
用户名、密码，**不支持完全没有 GUI 的 headless 会话**。它没有完整交易工作台，不代表
没有图形登录窗口，也没有可以直接替代登录的 API Key。

建议采用 **Xvfb 虚拟显示器 + 轻量窗口管理器 + VNC**：Java 窗口实际运行在 VPS 上，
用户通过 SSH 转发的 VNC 画面完成 Paper 登录及账户要求的认证。无需给服务器安装整套
GNOME 桌面。关闭 VNC 客户端不会主动退出 Gateway；Gateway 和虚拟显示器进程需要继续运行。
这是我们建议的部署方案，不能称为 IBKR 官方提供的无界面运行模式。

## 安装步骤

### 1. 准备虚拟图形环境

现有 VPS 是 Alibaba Cloud Linux 3、x86_64，使用 `dnf`，不照抄 Ubuntu 的 `apt` 命令。
需要的组件是 `xorg-x11-server-Xvfb`、`x11vnc`、`fluxbox` 和 `curl`。其中 `x11vnc`、
`fluxbox` 通常来自兼容的 EPEL 源；本次只查到公开包目录，尚未确认主机已启用的软件源。
先在主机确认这些包可用，再安装；不在这里预设添加其他发行版的软件源。

```bash
dnf list --available xorg-x11-server-Xvfb x11vnc fluxbox curl
dnf install -y xorg-x11-server-Xvfb x11vnc fluxbox curl
mkdir -p /opt/ibkr
```

安装与 Gateway 启动使用同一个运行用户及 `DISPLAY`。下面是首次安装时的手动步骤，
常驻运行时再由 systemd 管理显示器、VNC 和 Gateway，不把交互终端作为每日运行依赖。

在 VPS 启动显示器和窗口管理器，设置 VNC 访问密码并启动 VNC：

```bash
nohup Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/tmp/ibkr-xvfb.log 2>&1 &
nohup env DISPLAY=:99 fluxbox >/tmp/ibkr-fluxbox.log 2>&1 &
x11vnc -storepasswd /opt/ibkr/vnc.pass
x11vnc -display :99 -localhost -rfbport 5901 -rfbauth /opt/ibkr/vnc.pass -forever -shared -bg -o /tmp/ibkr-vnc.log
```

在自己的电脑建立转发，使用现有 SSH 别名：

```bash
ssh -N -L 15901:127.0.0.1:5901 megalog
```

用 VNC 客户端连接 `127.0.0.1:15901`。macOS 可在 Finder 的“前往 → 连接服务器”输入
`vnc://127.0.0.1:15901`；终端里的 SSH 转发保持运行。

### 2. 下载并安装 Gateway

打开 [官方下载页](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)，
选择 **Stable → Linux (X86_64)**。当前官方下载链接对应的命令为：

```bash
cd /opt/ibkr
curl -fL https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh -o ibgateway-installer.sh
chmod +x ibgateway-installer.sh
DISPLAY=:99 ./ibgateway-installer.sh
```

随后在 VNC 画面完成安装向导，记下实际安装目录和版本。Stable 安装包不会自动更新，
以后升级时记录 Gateway 版本，并重新验证与 SDK 的兼容性。
这些命令使用官方安装器，虚拟显示器和 VNC 的搭建则是我们的 Linux 部署步骤。

### 3. 登录并配置 API

1. 启动 Gateway，选择 **Paper Trading**，如出现接口类型选择则选 **IB API**。
   用户在 VNC 窗口输入自己的凭据并完成账户要求的认证，不需要把凭据发到聊天。
2. 打开 API 配置，确认 Socket Port 为 **4002**。若使用 TWS，则启用
   **Enable ActiveX and Socket Clients**，Paper 默认端口为 **7497**。
   端口可以改，项目配置必须与界面一致。
3. 第一阶段保留 **Read-Only API**，先验证账户、持仓、现金和行情。官方下单示例要求关闭
   只读开关；我们在进入 Paper 订单联调时再关闭。SDK 的 `readonly=True` 不能代替这个开关。
4. Python 适配器与 Gateway 同机连接 `127.0.0.1:4002`，不需要把 API 端口暴露给公网。
   M4 使用固定且独立的 `clientId`，并核对返回的是 Paper 账户。
5. 在 Lock and Exit 设置中配置每日 **Auto restart**。会话失效或每周需要重新认证时，
   用户再次通过 VNC 登录；进程自动重启、SDK 自动重连都不能代替这次认证。

2026-10-23 15:34（北京时间）已使用 `ib_async==2.1.0` 在 VPS 成功建立
`127.0.0.1:4002` 的 API 会话，返回一个 Paper 账户，
见[检查记录](https://github.com/wayslog/invest/actions/runs/39918594479)。
本次不检查具体 GUI 安装方式、自启动或每周认证流程；行情权限与订单联调仍待验收。
M3 原有账户和定时运行继续保持现状，Gateway 安装本身不切换资金账本或订单来源。

## 官方依据

- [API 简介](https://www.interactivebrokers.com/docs/tws-api/doc/introduction)：连接登录后的 TWS 或 Gateway。
- [下载 TWS 或 Gateway](https://www.interactivebrokers.com/docs/tws-api/doc/trader-workstation-and-ib-gateway/download-tws-or-ib-gateway)：两者二选一。
- [Gateway 架构与登录要求](https://www.interactivebrokers.com/docs/tws-api/doc/architecture/the-trader-workstation/the-ib-gateway)：图形登录、headless 限制及每日重启。
- [Gateway 下载](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)：Stable/Linux 安装器。
- [API 设置](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/introduction)：Socket 与只读配置。
- [每日与每周重新认证](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/daily-weekly-reauthentication)：自动重启与手动重新登录。

公开页面回执保存在忽略目录 `reports/access/ibkr-install-2026-10-23/`，格式为 Parquet/Zstandard。
