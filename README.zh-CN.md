### myapp

这是一个基于 Frappe / ERPNext 的自定义应用。

语言版本：

- English: `README.md`
- 简体中文: `README.zh-CN.md`

文档导航：

- API 说明：`API_GATEWAY.md`
- 中文 API 说明：`API_GATEWAY.zh-CN.md`
- 中文测试说明：`TESTING.zh-CN.md`
- 报表模块设计文档：`REPORTS_TECH_DESIGN.zh-CN.md`
- 开发设计基准文档：`WHOLESALE_TECH_DESIGN.zh-CN.md`
- 采购与进货流程设计文档：`PURCHASE_TECH_DESIGN.zh-CN.md`
- 扫码识别与条码多源解析设计文档：`BARCODE_SCANNING_TECH_DESIGN.zh-CN.md`

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

当前开发环境约定：

- 项目以 VS Code devcontainer / Docker 中的 ERPNext 运行环境为主，不以宿主机 WSL 直接运行 Frappe 代码为准
- 若需要做接口联调或冒烟测试，优先通过 HTTP 访问宿主机 `http://localhost:8080`
- 宿主机侧脚本请使用 `python3`，不要默认使用 `python`

### HTTP 测试

对于 `myapp.api.gateway.*` 这类接口，建议优先使用 HTTP 方式测试，而不是在 WSL 宿主机里直接导入项目服务层执行。

已提供测试文件：

- `myapp/tests/http/test_gateway_http.py`
- `myapp/tests/http/test_gateway_v2_http.py`

已提供环境变量示例文件：

- `.env.http-test.example`

推荐步骤：

1. 复制示例文件为 `.env.http-test`
2. 填入测试地址以及测试账号密码或 API Token
   - 宿主机执行时：`http://localhost:8080`
   - backend 容器内直接执行时：`http://localhost:8000`
3. 在仓库根目录执行 `python3 apps/myapp/myapp/tests/http/test_gateway_http.py`

说明：

- 测试文件会优先读取环境变量；如果未显式传入，也会自动尝试读取 `apps/myapp/.env.http-test`
- 宿主机默认地址是 `http://localhost:8080`
- backend 容器内直接执行时，应改用 `http://localhost:8000`
- 不要改成 `127.0.0.1`，保持与当前 devcontainer 约定一致
- 建议优先使用 API Token，而不是长期使用管理员密码
- 当前 HTTP 测试已覆盖所有 `myapp.api.gateway.*` 接口的基础可达性 / 鉴权后响应结构
- 当前已补充销售主链路与采购主链路的真实成功测试
- 当前已补充销售侧与采购侧的顺序幂等、不同数据、并发幂等测试
- 当前已补充 v2 商品与销售状态聚合接口的真实 HTTP 测试
- 大多数基础用例只验证成功结构或校验错误结构，不依赖固定业务单据，适合日常冒烟检查
- 测试会默认打印接口返回值，并把结果保存到 `apps/myapp/http-test-results.json`
- 可通过 `MYAPP_HTTP_PRINT_RESPONSES` 和 `MYAPP_HTTP_SAVE_RESPONSES` 控制是否打印或保存
- 若多接口联调需要串联参数，可直接从结果文件中读取上一个接口返回值
- 当前主链路测试已改为“单个测试自建前置数据”，不再依赖固定执行顺序或历史结果文件
- 已重新验证单个方法、销售链路、采购链路、幂等/并发和整份文件全量执行
- `python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_http` 当前最新全量结果为 `Ran 49 tests in 33.298s ... OK`
- `python3 -m unittest apps.myapp.myapp.tests.http.test_gateway_v2_http` 当前最新全量结果为 `Ran 119 tests in 55.746s ... OK`

更完整的当前覆盖范围、权限要求和本轮测试结论，请参见 `TESTING.zh-CN.md`。

本次测试工作额外说明：

- 销售侧和采购侧主链路均已在真实 HTTP 环境中跑通
- 日志中若出现 `422`，需要区分是否为预期业务校验失败；探测不存在主数据时返回 `422` 并不代表主链路失败
- 当前测试已足够覆盖现阶段核心场景，部分收货 / 部分开票 / 部分退货等更复杂边界可后续补充

如果只想跑单个接口测试，可以直接指定方法：

```bash
python3 apps/myapp/myapp/tests/http/test_gateway_http.py \
  GatewayHttpTestCase.test_search_product_with_empty_query_returns_success_shape
```

当前测试目录建议：

- `myapp/tests/http/`：HTTP 冒烟、链路、幂等、并发测试
- `myapp/tests/unit/`：服务层与工具函数单元测试
- `myapp/tests/integration/`：依赖真实站点上下文的服务链路回归测试

当前新增的销售单位换算 / 库存结算回归测试：

- `myapp/tests/integration/test_sales_uom_stock_chain.py`

推荐在 backend 容器中运行：

```bash
docker exec frappe_docker-backend-1 bash -lc '
  cd /home/frappe/frappe-bench &&
  env/bin/python -m unittest apps.myapp.myapp.tests.integration.test_sales_uom_stock_chain
'
```

这组回归主要覆盖：

- 批发单位建单并发货
- 零售单位建单并发货
- 修改订单单位 / 数量后再发货
- 批发单位库存不足时发货被拦截，且库存不变

重点校验：

- `Sales Order Item.stock_qty`
- `Bin.actual_qty`
- `Stock Ledger Entry.actual_qty`

也就是说，它不只检查“订单里算得对”，还会检查“发货后真实库存是否按库存单位准确结算”。

当前商品创建接口补充说明：

- `create_product_v2` 已支持原子化“建商品 + 初始化库存”
- 当前可在一次请求内同时提交：
  - 商品主数据
  - `warehouse`
  - `warehouse_stock_qty`
  - `warehouse_stock_uom`
- 若同时传入仓库与初始库存，后端会在创建商品后立即完成该仓库存初始化
- 若不传库存初始化字段，则仍保持原来的“纯建档”语义
- 因此移动端当前不需要再分两次调用“先建商品、再调库存调整”，可以直接一次提交完成

当前商品图片上传约定：

- 商品主数据仍继续使用 ERPNext 标准字段 `Item.image`
- 新增统一媒体上传入口：`myapp.api.gateway.upload_item_image`
- 新增安全替换入口：`myapp.api.gateway.replace_item_image`
- 当前上传实现先走 Frappe / ERPNext 自带 `File` 存储，并返回 `file_url`
- 商品创建 / 编辑接口仍只接收 `image` 字段，不直接感知底层存储提供方
- 替换商品图片时，后端会优先只清理“由当前商品 `image` 字段托管且未被其他商品复用”的旧文件，降低幽灵文件和误删风险
- 后续若切换 MinIO / OSS / S3，优先只替换媒体服务内部实现，尽量不改商品业务接口契约

当前主数据补充说明：

- 单位模块接下来会进入一轮“临时统一性优化”
- 当前问题主要是部分页面仍依赖前端本地英文单位映射，容易出现中英文混用
- 这一轮会优先从后端接口补统一的单位显示字段，先收敛商品与 UOM 主数据相关页面的显示混乱
- 这次优化以“先统一显示契约”为目标，暂不做大范围历史主数据重构

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

- `myapp.services.customer_service`
- `myapp.services.order_service`
- `myapp.services.settlement_service`
- `myapp.services.wholesale_service`

已验证模块：

- `myapp.services.customer_service`
- `myapp.services.uom_service`
- `myapp.api.gateway`
- `myapp.services.order_service`
- `myapp.services.settlement_service`

当前新增的主数据模块：

- 客户管理后端：
  - `list_customers_v2`
  - `get_customer_detail_v2`
  - `create_customer_v2`
  - `update_customer_v2`
  - `disable_customer_v2`
- 单位管理后端：
  - `list_uoms_v2`
  - `get_uom_detail_v2`
  - `create_uom_v2`
  - `update_uom_v2`
  - `disable_uom_v2`
  - `delete_uom_v2`

其中单位管理当前补充了两条保护规则：

- 已被引用的单位不允许直接删除，建议走停用
- 已被引用的单位不允许直接修改 `must_be_whole_number`
- `myapp.services.wholesale_service`

已验证方法：

- `list_customers_v2`
- `get_customer_detail_v2`
- `create_customer_v2`
- `update_customer_v2`
- `disable_customer_v2`
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
