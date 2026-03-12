### myapp

new app

Language:

- English: `README.md`
- 简体中文: `README.zh-CN.md`

Documentation:

- API reference: `API_GATEWAY.md`
- Chinese API reference: `API_GATEWAY.zh-CN.md`
- Technical design baseline: `WHOLESALE_TECH_DESIGN.zh-CN.md`
- Purchasing and inbound flow design: `PURCHASE_TECH_DESIGN.zh-CN.md`

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app myapp
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/myapp
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

Current development environment assumptions:

- The primary runtime is the VS Code devcontainer / Docker-based ERPNext environment, not direct Frappe execution from the host WSL environment.
- For API validation and smoke tests, prefer HTTP requests against `http://localhost:8080`.
- Use `python3` on the host side instead of assuming a `python` command is available.

### HTTP Testing

For `myapp.api.gateway.*` endpoints, prefer HTTP-based testing from the host instead of importing the Frappe service layer directly in WSL.

Provided test file:

- `myapp/tests/http/test_gateway_http.py`

Provided environment example:

- `.env.http-test.example`

Recommended flow:

1. Copy `.env.http-test.example` to `.env.http-test`.
2. Fill in `http://localhost:8080` and either login credentials or API token values.
3. Run `python3 apps/myapp/myapp/tests/http/test_gateway_http.py` from the repo root.

Notes:

- The test file reads environment variables first and then falls back to `apps/myapp/.env.http-test`.
- The default base URL is `http://localhost:8080`.
- Keep the host as `localhost` to match the current devcontainer setup.
- Responses are printed and also saved to `apps/myapp/http-test-results.json`.
- The current HTTP test suite already covers sales and purchase flow happy paths, idempotent replay, different-data cases, and concurrent idempotency checks.

### Service Validation

The service layer under `myapp/api/` was validated in a VS Code devcontainer / ERPNext v16 environment through `bench console`.

Recommended public API entry points:

- `myapp.api.gateway.create_order`
- `myapp.api.gateway.submit_delivery`
- `myapp.api.gateway.create_sales_invoice`
- `myapp.api.gateway.search_product`
- `myapp.api.gateway.confirm_pending_document`
- `myapp.api.gateway.update_payment_status`
- `myapp.api.gateway.process_sales_return`

Backward-compatible aggregate path:

- `myapp.api.api.*`

Service implementation modules:

- `myapp.services.order_service`
- `myapp.services.settlement_service`
- `myapp.services.wholesale_service`

Validated modules:

- `myapp.api.gateway`
- `myapp.services.order_service`
- `myapp.services.settlement_service`
- `myapp.services.wholesale_service`

Validated methods:

- `create_order`
- `submit_delivery`
- `create_sales_invoice`
- `search_product`
- `update_payment_status`
- `process_sales_return`

Validated happy-path sample:

- `customer="Palmer Productions Ltd."`
- `item_code="SKU010"`
- `warehouse="Stores - RD"`
- `company="rgc (Demo)"`

Example validation flow:

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

Observed business constraints during validation:

- Warehouse must belong to the same company as the order.
- `immediate=True` requires available stock in the selected warehouse.
- If no `Bin` exists for an `item_code + warehouse` pair, the service treats available stock as `0` and blocks immediate delivery.

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
