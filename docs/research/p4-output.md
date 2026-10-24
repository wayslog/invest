# P4：选股动作、统一报告与入口清理

日期：2026-10-24。状态：P4 本地离线验收通过。
本阶段完成三个研究入口的离线闭环；不修改持续账户，不发送或取消券商订单，不部署。

## 使用

```bash
make quant-demo P4_DEMO_DIR=reports/my-new-quant-demo
uv run --locked --group research invest decide \
  --config reports/my-new-quant-demo/decide.toml \
  --as-of 2022-12-30 --output reports/my-new-decision
uv run --locked --group research invest verify-decision --study reports/my-new-decision
```

演示使用合成行情：先执行 `mine`、`backtest`，再从该回测的决策前状态生成 `decide` 建议，
并逐行比较动作及动作 ID。日期是明确的研究截点，不是声称当年实际发布过这些建议。
正式运行保存真实创建时间；漏跑会话不能被补造为当时已发布的计划。
输出目录必须不存在，失败记录保留；重新运行用新目录，不覆盖旧研究。

三个命令均输出 JSON 摘要，诊断日志写标准错误，HTML 路径在 `report` 字段中。
`mine` 全部淘汰、`decide` 无合格信号时返回退出码 1；输入或执行错误返回 2。
没有信号时仍保存 `insufficient_evidence`、排名覆盖与 WAIT/已有退出需求，不产生虚假买入。

## 冻结策略与账户输入

`decide.toml` 只有四项，路径相对配置文件：

```toml
strategy = "research/backtest"
snapshot = "research/backtest/inference"
context = "research/backtest/decision_contexts.parquet"
known_through = 2022-12-30
```

- `strategy` 是已完成回测目录。校验完整产物清单、配置、金融行为版本和依赖，读取其
  因子池及 Policy。不能在当前决策中悄悄改止损、风险预算或因子方向。
- `snapshot` 是 P1 Parquet 快照。只用截至 `--as-of` 的前缀计算，完整来源、范围和原有
  缺口同时保存。未来行的缺口不改变过去因子准入；研究调整价不能当作原价账本。
- `context` 是 `decision_io.CONTEXT_SCHEMA` 的 Parquet 账户与策略状态，必须恰好有一行
  匹配决策日期。可使用 P4 回测产生的 `decision_contexts.parquet` 或 `final_context.parquet`；
  前者是决策前状态，后者带期末待处理订单，因而可能正确地产生 WAIT。
- 表 metadata 必须包含匹配的 `policy_id`、`pool_id`、`price_basis=raw`、非空 `source_ref`，
  以及 `context_kind=backtest_simulation` 或 `declared_snapshot`。账户自身的 `snapshot_id`
  和 `source` 必须与研究快照一致。原价研究进一步逐项核对可用报价。

原始 P4 使用有来源依据的 `declared_snapshot`；现已新增 `broker_capture` 配置，
将完整 IBKR 采集与持久账户状态核对后生成上下文，详见[筛选与账户适配](research-screening-and-broker-context.md)。
手工声明不会升级成券商确认。金额、成本锚点、持仓高点、
入场日期、风险状态、待处理单、分红应收和未结算现金必须保留，不允许用一份新本金替代旧状态。
调整价研究中的原价报价与企业行动仍需原始来源证明，研究浮点缓存不能反向重建这些字段。

收到晚于收盘才可得的报价时，该报价被降为不可用；已有持仓的未知估值会阻止新增风险。
这也暂停依赖组合净值的调仓与敞口减仓，但不阻止有可靠报价支持的独立退出。
对应动作的未知权重、不可用参考价为空；已有待买单必须重新满足买入准入，
`cancel_pending` 只是取消建议，确认取消前仍保留原资金和敞口占用。
暂停、风险锁与待处理订单继续由 `strategies.decide` 处理。账户输入只复制、校验，不回写。
`effective_context.parquet` 是本次准入后的输入视图，`proposed_context.parquet` 是建议状态预览；
二者都标为 `decision_preview`，不能未经实际成交与状态核对就作为下次权威账户输入。

已知历史取本次声明、原回测声明和原回测 `consumed_through` 的最大值，不能用较早日期
重新取得样本外资格。本次截点另记为 `consumed_through`；后续研究应带上已查看的记录。
来源的探索范围、原留出状态、因子池范围和所有限制均保留。

## 结果

| 文件 | 用途 |
| --- | --- |
| `rankings.parquet` | 股票身份、评分、排名、目标持有状态、动作和原因、可用/必需因子数、覆盖与收盘截点 |
| `factors.parquet`、`contributions.parquet` | 实际计算信号的原值、时点、横截面秩、方向、权重和评分贡献；缺失不能伪装成零贡献 |
| `signals.parquet` | 同 P2/P3 的冻结信号；评分不是获利概率 |
| `actions.parquet` | 同一个 `decide` 的结果，含 BUY/ADD/TRIM/SELL/HOLD/WAIT、股数、参考价、退出条件、有效期、取消待单需求及版本引用 |
| `context.parquet`、`effective_context.parquet`、`proposed_context.parquet` | 原输入、时点准入后的视图和建议状态；没有账本提交 |
| `registration.parquet`、`run.parquet`、`artifacts.parquet` | 登记、完成或失败状态、输入与配置摘要、来源、已知历史、源码及依赖、完整文件清单 |
| `strategy/`、`snapshot/`、`inference/`、`engine/`、`config.toml` | 冻结原回测、来源、因果前缀、当前源码与配置；有锁文件时同时保存 `uv.lock` |
| `report.html` | 中文可读报告；展示正式结果，不充当另一份权威数据 |

动作使用 `invest.research.actions.v2`，补充 `price_type=next_session_open`、`exit_mode`、
`max_holding_sessions`、`cooldown_sessions`。止损止盈为决策时参考，新建/加仓后的成本和
保护线必须按实际成交重新计算；跳空可能越过止损。保护模式不表示已经向券商挂出保护单。
WAIT 与 `exit_reason`、`cancel_pending` 一起看，不能把未能执行的退出理解成风险已解除。
排名中的 `selected` 表示目标持有，不表示该股票本次一定新增买入；高排名超配可以减仓。

回测报告显示四个情景、成本后净值/回撤、分年结果、完整交易胜负、R 与独立对账。
挖掘报告显示全部尝试、淘汰原因和冻结池；因子全部淘汰时仍生成报告。
报告表格显示最多前 100 行并链接完整 Parquet；时间显示北京时间，Parquet 保存 UTC。
收益率、覆盖率、权重为比例，金额是美元，股数为整股。

## 清理与版本

默认 `invest --help` 只展示三项主流程、两项验证命令及显式 `legacy` 入口。
旧 `analyze/paper/audit/fetch/verify-data`、分红工具、M2/R1 研究命令从主列表移除，
改为 `invest legacy <原命令>`。`forward-*` 原调用方式继续委派原操作实现；`invest-ibkr` 不变。
冻结旧源码中的旧 CLI 保持原样，不要求历史包识别新前缀。

旧趋势和轮动移到 `legacy_strategies.py`，原 Python 导入名兼容保留。
共享组合模式提到 `portfolio_types.py`，新回测不再通过旧模拟器取得类型。
`quant_report.py` 统一三个阶段展示；旧报告模块仅服务历史工作流。
现有 `paper`、`portfolio`、M2/R1 和 forward 的旧实现仍有兼容调用，保留其原语义与重放职责；
清理没有转化为对已部署账户的隐式迁移。

新研究保存完整 `engine_digest` 和独立 `financial_digest`。
后者排除明确的 CLI/报告文件，允许纯展示修改后验证同一金融结果；策略、会计、数据契约、
配置或执行模块变化仍使它失效。原账户 `engine_digest` 算法不变，仍绑定全部源码。
新行为不能覆盖旧产物；版本不一致时使用研究目录中冻结源码和相同依赖重放。

## 验收与真实数据边界

验收证据位于 `reports/p4-validation-20261024/`；最终源码共 60 个 Python 文件，
完整摘要为 `e59f7b5885f4d8aaee588d558c6a5c40ae40e16eb35a561f270e22099c1a1d92`。

| 检查 | 结果与证据 |
| --- | --- |
| P4 专项 | 13 项通过，含当前/回测动作一致、贡献解释、暂停及待单、晚到行情、输入来源/时点、未来隔离、版本分离、历史目录保护和冻结期间替换；`freezing-green.log` |
| `make check` | Ruff、格式、mypy 通过；462 项测试通过，788.51 秒；项目源码覆盖率 87%；`check-final.log`、`source-coverage.log` |
| 新全链路 | `reports/p4-final-20261024/`；18 个候选保留 1 个因子，516 条历史信号/动作、16 笔模拟成交、6 个完整周期，12 条当前排名/贡献/动作；`quant-demo-final.log` |
| 独立审计与格式 | 四情景 7,702 项账务检查通过；186 个 Parquet 文件均使用 Zstandard；三个阶段分别校验 94、125、208 个冻结文件；`artifact-final.parquet` |
| P4 冻结源码 | 从 `decision/engine` 加载原包，只读重放当前决策和回测通过；`frozen-replay-final.log` |
| P3 原版重放 | 从 P3 冻结包重放原回测及旧 M2 的 69 次运行通过；`p3-frozen-replay.log` |
| M1 / 旧研究 | 新目录 `reports/p4-paper-final-20261024/`、`reports/p4-legacy-final-20261024/`，旧研究 69 次重算通过；`paper-demo-final.log`、`legacy-demo-final.log` |
| 前向合成演练 | 新目录 `reports/p4-forward-final-20261024/`，106 项对账通过；`forward-demo-final.log` |
| 历史保护 | 改动前登记的 4,284 个数据与研究文件摘要全部不变；`history-before.parquet`、`artifact-final.parquet` |
| 包构建 | 最终 wheel、sdist 和包内源码核对见 `build-final.log`、`package-verification.parquet`；版本仍为 0.7.1，不表示发布 |

`check.log` 是补充冻结一致性回归前主动中断的早期全套检查，不作为通过证据。
早期 `reports/p4-accepted-20261024/` 及其日志保留，仅最终 `p4-final-20261024` 目录对应上述源码。
`freezing-red.log` 保留复制期间策略来源错配的失败回归；其他 `*-red.log` 保留开发失败证据。
缓存和本轮新增输出不列入改动前历史基线；不会为了通过验收删除早期结果。
全套检查的原始覆盖率汇总包含版本测试复制的第二份源码，显示为 44%；只计项目源码为 87%。
随后只调整该测试副本到已有的 `changed-engine` 隔离目录，相关用例在开启覆盖率时通过，
统计恢复为单份 6,789 条语句，见 `coverage-fixture.log`；Ruff、格式和 mypy 再次通过。
业务源码仍与全套检查和最终演示的 60 个文件摘要一致。


| 证据类别 | 本阶段提供 | 仍需另行取得 |
| --- | --- | --- |
| 工程 | 合成离线闭环、动作一致性、重放、会计核对、时点与输入验证 | 外部接入端的实际验收 |
| 数据 | 保留 IBKR/合成/历史参考来源与缺口；原价上下文和因子时点核对 | 真实历史股票池、发布时间、企业行动、单位及账户导出证据 |
| 策略 | 成本后回测、参考组合、完整交易评价；全部失败可以保留 | 独立测试、多重试验处理、足够样本及真实执行能力 |

所有新研究的 `account_eligible` 仍为 false。P4 不自动发出盈利结论或实盘资格。

后续 P3/P4 审阅修复及验收见 [修复记录](p3-p4-review-fixes.md)；本节原始验收证据保持不变。
