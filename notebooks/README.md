# 探索性研究

Notebook 用于验证想法，复用逻辑应迁入 `src/invest/` 并添加测试。
当前基础环境不安装 Jupyter；需要时用 `uv add --group research jupyterlab matplotlib`
显式加入研究依赖，并提交更新后的 `pyproject.toml` 和 `uv.lock`。
提交 Notebook 前清理含有账户信息或凭据的单元格及输出。
