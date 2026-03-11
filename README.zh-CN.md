### myapp

这是一个基于 Frappe / ERPNext 的自定义应用。

语言版本：

- English: `README.md`
- 简体中文: `README.zh-CN.md`

文档导航：

- API 说明：`API_GATEWAY.md`
- 中文 API 说明：`API_GATEWAY.zh-CN.md`
- 开发设计基准文档：`WHOLESALE_TECH_DESIGN.zh-CN.md`
- 采购与进货流程设计文档：`PURCHASE_TECH_DESIGN.zh-CN.md`

### 安装

可以使用 [bench](https://github.com/frappe/bench) CLI 安装此应用：

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app myapp
```

### 开发

本应用使用 `pre-commit` 做格式化和静态检查。请先安装并启用：

```bash
cd apps/myapp
pre-commit install
```

当前 `pre-commit` 配置包含：

- ruff
- eslint
- prettier
- pyupgrade

### 服务验收

`myapp/api/` 下的服务层已经在 VS Code devcontainer / ERPNext v16 环境中通过 `bench console` 做过真实验证。

推荐的对外接口入口：

- `myapp.api.gateway.create_order`
- `myapp.api.gateway.submit_delivery`
- `myapp.api.gateway.create_sales_invoice`
- `myapp.api.gateway.search_product`
- `myapp.api.gateway.confirm_pending_document`
- `myapp.api.gateway.update_payment_status`
- `myapp.api.gateway.process_sales_return`

兼容保留的聚合路径：

- `myapp.api.api.*`

服务实现模块：

- `myapp.services.order_service`
- `myapp.services.settlement_service`
- `myapp.services.wholesale_service`

已验证模块：

- `myapp.api.gateway`
- `myapp.services.order_service`
- `myapp.services.settlement_service`
- `myapp.services.wholesale_service`

已验证方法：

- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `search_product`
- `update_payment_status`
- `process_sales_return`

已验证成功的样例参数：

- `customer="Palmer Productions Ltd."`
- `item_code="SKU010"`
- `warehouse="Stores - RD"`
- `company="rgc (Demo)"`

验收调用示例：

```python
from myapp.api.gateway import create_order, process_sales_return, update_payment_status

result = create_order(
	customer="Palmer Productions Ltd.",
	items=[
		{
			"item_code": "SKU010",
			"qty": 1,
			"warehouse": "Stores - RD",
		}
	],
	company="rgc (Demo)",
	immediate=True,
)

payment_result = update_payment_status(
	reference_doctype="Sales Invoice",
	reference_name=result["sales_invoice"],
	paid_amount=1,
)

return_result = process_sales_return(
	source_doctype="Sales Invoice",
	source_name=result["sales_invoice"],
)
```

本次验收过程中确认的业务约束：

- 仓库必须属于与订单相同的公司。
- `immediate=True` 需要所选仓库具备可用库存。
- 如果某个 `item_code + warehouse` 组合不存在 `Bin` 记录，服务层会按可用库存 `0` 处理，并阻止即时发货。

### CI

本应用可使用 GitHub Actions 做持续集成，当前已配置：

- CI：在推送到 `develop` 分支时安装应用并运行单元测试
- Linters：在 Pull Request 上运行 [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) 和 [pip-audit](https://pypi.org/project/pip-audit/)

### 许可证

mit
