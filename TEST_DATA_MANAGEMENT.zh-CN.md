# 测试数据管理设计与使用说明

更新时间：2026-07-21

## 1. 定位

MyApp 测试数据管理用于开发、测试和演示环境生成可重复、可审计的标准业务数据。它不替代自动化测试自行创建前置数据，也不提供任意公司清库能力。

首期内置数据集：

- 代码：`standard-wholesale-small`
- 版本：`2026.07-v1`
- 范围：4 个商品、4 个客户、3 个供应商、5 个销售场景、3 个采购场景
- 覆盖：多 UOM、订单未履约、部分发货、未收款、已收款、完整销售、采购未收货、已收货、部分付款

支持三种应用级模式：

- `generate`：在空白范围首次生成完整基线。
- `supplement`：复用系统登记拥有的标准主数据，只追加选定业务场景。
- `reset`：清理该数据集所有活动对象并重建完整基线。

支持三种数据量档位，数据集代码仍表示稳定模板身份，档位由每次运行的 `scale` 决定：

- `small`：每个选定场景 1 份，适合日常功能测试。
- `medium`：每个选定场景 5 份，适合列表、筛选和批量操作测试。
- `large`：每个选定场景 20 份，适合性能和容量测试，也是系统允许的硬上限。

主数据无论档位大小都只创建一次，交易场景按档位重复。每个场景实例使用如 `sales-open#1`、`sales-open#2` 的独立登记键，并按份数逐日错开业务日期。首次生成或重建时，期初库存数量按场景份数放大，但仍只创建一张期初库存单据，保证完整履约场景有足够库存。

## 2. 安全边界

写操作同时满足以下条件才会执行：

1. 当前用户是 `Administrator` 或拥有 `System Manager` 角色。
2. `myapp_test_data_enabled` 显式启用。
3. `myapp_environment_type` 是 `development`、`test`、`testing` 或 `demo`。
4. 目标公司位于 `myapp_test_data_allowed_companies` 白名单。
5. 目标仓库存在并属于目标公司。
6. 用户提交准确的确认文本，例如 `RESET rgc (Demo)`。
7. 同一公司没有其他测试数据任务运行。

即使启用了 Frappe `developer_mode`，缺少上述显式配置时仍会失败关闭。生产环境不得配置这些开关。

## 3. 站点配置

开发站点示例：

```bash
bench --site localhost set-config myapp_test_data_enabled 1
bench --site localhost set-config myapp_environment_type development
bench --site localhost set-config --parse myapp_test_data_allowed_companies '["rgc (Demo)"]'
```

可选覆盖 ERPNext 默认主数据：

```bash
bench --site localhost set-config myapp_test_data_customer_group "Demo Customer Group"
bench --site localhost set-config myapp_test_data_territory "China"
bench --site localhost set-config myapp_test_data_supplier_group "Demo Supplier Group"
bench --site localhost set-config myapp_test_data_item_group "Demo Item Group"
```

没有覆盖时，生成器读取 Selling Settings、Buying Settings 和 Stock Settings 的默认值。

## 4. 命令行

命令必须在 Backend 容器的 bench 环境运行：

```bash
cd /home/frappe/frappe-bench
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  preview \
  --company "rgc (Demo)" \
  --warehouse "主仓库 - R"
```

同步生成：

```bash
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  generate \
  --company "rgc (Demo)" \
  --warehouse "主仓库 - R"
```

只补充一个销售未付款场景：

```bash
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  supplement \
  --scenario sales-unpaid \
  --company "rgc (Demo)" \
  --warehouse "主仓库 - R"
```

`--scenario` 可以重复传入。补充模式要求完整基线已经存在，并拒绝复用不属于测试数据登记表的同名主数据。

补充 5 份销售未履约订单，用于列表和批量操作测试：

```bash
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  supplement \
  --scenario sales-open \
  --scale medium \
  --company "rgc (Demo)" \
  --warehouse "主仓库 - R"
```

清理由测试数据登记表拥有的对象并重建：

```bash
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  reset \
  --company "rgc (Demo)" \
  --warehouse "主仓库 - R"
```

增加 `--enqueue` 可改为长队列后台执行。可通过 `status --run <run_name>` 查询状态，通过 `validate --company ...` 重新执行完整性验证。

## 5. API

- `myapp.api.test_data_api.list_test_datasets_v1`
- `myapp.api.test_data_api.preview_test_dataset_v1`
- `myapp.api.test_data_api.request_test_dataset_run_v1`，仅 POST
- `myapp.api.test_data_api.get_test_dataset_run_v1`
- `myapp.api.test_data_api.list_test_dataset_runs_v1`
- `myapp.api.test_data_api.validate_test_dataset_v1`，仅 POST

Web 页面在调用写接口前必须先调用 preview，显示环境、公司、仓库、数据量档位、场景份数、场景实例数、预计数量、冲突、阻断原因和确认文本。补充模式通过 `scenario_keys` 传入一个或多个场景代码，通过 `scale` 传入 `small`、`medium` 或 `large`。

Web 管理入口：

```text
/administration/test-data
```

该页面仅对 Web `canAdmin` 用户显示，后端仍独立执行 `System Manager` 权限校验，前端菜单权限不能替代服务端授权。

后台任务进度通过 Redis 临时缓存对轮询请求可见，任务结束后将最终进度持久化到运行审计表；业务数据事务不会为了展示进度而提前提交。

## 6. 重置语义

首期 `reset` 不是公司级清库。系统只删除 `MyApp Test Dataset Object` 中登记且仍属于测试数据运行的对象，并严格按创建顺序逆序执行：

```text
收付款 → 发票 → 发货/收货 → 订单 → 库存初始化 → 价格 → 商品 → 客户/供应商
```

已提交单据先通过 ERPNext 正式取消逻辑处理，再删除单据。如果测试数据被人工建立了额外下游引用，重置会失败并回滚，不会强制破坏引用。

后续公司级清理应封装 ERPNext `Transaction Deletion Record`，并仅允许专用测试公司使用；整站恢复则由父仓库的备份和部署层负责。

## 7. 完整性验证

生成完成前自动验证：

- 登记对象全部存在。
- 交易行具有 `uom`、`stock_uom` 和有效 `conversion_factor`。
- `stock_qty = qty × conversion_factor`。
- 测试商品库存不存在负数。
- 发票未结金额处于合法区间。
- 相关总账凭证借贷平衡。

任何检查失败时，运行状态标记为 `failed`，生成事务回滚并保存错误日志。

## 8. 公司级交易重置

当专用测试公司的数据来源复杂、已经无法通过模板对象 reset 恢复时，可以使用公司级交易重置。该能力封装 ERPNext 官方 `Transaction Deletion Record`，不会自行执行 SQL 清账。

公司级重置会删除目标公司下所有来源的交易数据，包括订单、发货/收货、发票、收付款、库存流水、库存 Bin、总账和付款台账；它会保留公司、科目、成本中心、仓库、客户、供应商、商品、付款方式、用户和系统配置。

该能力使用比模板数据管理更严格的独立开关和独立公司白名单：

```bash
bench --site localhost set-config myapp_company_transaction_reset_enabled 1
bench --site localhost set-config --parse \
  myapp_company_transaction_reset_allowed_companies '["Dedicated Test Company"]'
```

生产环境不得配置这些开关。公司必须同时处于允许的 `development`、`test`、`testing` 或 `demo` 环境中。

只读预检：

```bash
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  company-reset-preview \
  --company "Dedicated Test Company"
```

预检会返回涉及的 DocType、公司字段、预计记录引用数、当前模板登记对象数、保留的核心主数据和所有阻断原因。

创建不可逆删除任务：

```bash
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  company-reset \
  --company "Dedicated Test Company" \
  --confirmation "DELETE ALL TRANSACTIONS Dedicated Test Company" \
  --acknowledge-irreversible
```

任务由 ERPNext 长队列分批执行，可使用以下命令查询：

```bash
env/bin/python -m myapp.scripts.test_dataset \
  --site localhost \
  company-reset-status \
  --record "TDL.0001"
```

API：

- `preview_company_transaction_reset_v1`
- `request_company_transaction_reset_v1`，仅 POST
- `get_company_transaction_reset_v1`

执行前必须满足：

1. 当前用户为 `Administrator` 或 `System Manager`。
2. 独立危险开关已开启。
3. 公司位于公司级重置专用白名单。
4. 没有测试数据任务或其他 ERPNext 交易删除任务正在执行。
5. 输入完整确认文本。
6. 明确勾选“不可逆且已准备必要备份”。

公司交易删除完成后，测试数据登记表中可能保留指向已删除交易的历史记录。随后执行标准测试数据 `reset` 时，系统会自动核销这些失效登记、删除仍保留的模板主数据并重建完整基线。

公司级重置不等于整站重建。整个 Site 严重污染时，仍应由部署层恢复黄金快照或重建 Site。

### 8.1 临时 Site 破坏性验收注意事项

在 Docker 多容器环境新建临时 Site 时，Backend、Long Worker 和 Short Worker来自不同容器地址。临时数据库用户必须允许这些应用容器连接，例如创建 Site 时使用适合当前隔离网络的 `--mariadb-user-host-login-scope`；否则 Backend 能创建任务，但 Worker 会因数据库用户来源地址不匹配而失败。

数据库备份不会包含原 Site 的 `site_config.json`。恢复到临时 Site 后，需要显式复制以下运行配置：

- `encryption_key`
- 测试环境类型和危险开关
- 普通测试数据及公司级重置白名单
- `myapp_test_data_customer_group`
- `myapp_test_data_territory`
- `myapp_test_data_supplier_group`
- `myapp_test_data_item_group`

临时 Site 验收结束后必须删除临时 Site、数据库、数据库用户、归档目录和备份文件，并重新验证原 Site 未受影响。
