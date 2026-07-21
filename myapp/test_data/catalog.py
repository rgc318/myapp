from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ItemTemplate:
	key: str
	item_code: str
	item_name: str
	stock_uom: str
	opening_qty: float
	standard_rate: float
	uom_conversions: tuple[tuple[str, float], ...]
	wholesale_default_uom: str
	retail_default_uom: str


@dataclass(frozen=True)
class PartyTemplate:
	key: str
	name: str


@dataclass(frozen=True)
class ScenarioTemplate:
	key: str
	domain: str
	state: str
	party_key: str
	item_key: str
	qty: float
	uom: str
	rate: float
	date_offset_days: int
	partial_qty: float | None = None
	payment_ratio: float | None = None


@dataclass(frozen=True)
class DatasetDefinition:
	code: str
	version: str
	scale: str
	label: str
	description: str
	items: tuple[ItemTemplate, ...]
	customers: tuple[PartyTemplate, ...]
	suppliers: tuple[PartyTemplate, ...]
	scenarios: tuple[ScenarioTemplate, ...]

	def serialize(self) -> dict:
		return asdict(self)


STANDARD_WHOLESALE_SMALL_V1 = DatasetDefinition(
	code="standard-wholesale-small",
	version="2026.07-v1",
	scale="small",
	label="标准批发业务小型数据集",
	description="覆盖多单位商品、销售履约、销售结算、采购收货和采购结算的确定性测试数据。",
	items=(
		ItemTemplate(
			key="rice",
			item_code="TDM-SWS-V1-RICE",
			item_name="测试大米 5kg",
			stock_uom="Nos",
			opening_qty=360,
			standard_rate=68,
			uom_conversions=(("Nos", 1), ("Box", 12)),
			wholesale_default_uom="Box",
			retail_default_uom="Nos",
		),
		ItemTemplate(
			key="oil",
			item_code="TDM-SWS-V1-OIL",
			item_name="测试食用油 5L",
			stock_uom="Nos",
			opening_qty=240,
			standard_rate=92,
			uom_conversions=(("Nos", 1), ("Box", 6)),
			wholesale_default_uom="Box",
			retail_default_uom="Nos",
		),
		ItemTemplate(
			key="water",
			item_code="TDM-SWS-V1-WATER",
			item_name="测试饮用水",
			stock_uom="Nos",
			opening_qty=600,
			standard_rate=3,
			uom_conversions=(("Nos", 1), ("Box", 24)),
			wholesale_default_uom="Box",
			retail_default_uom="Nos",
		),
		ItemTemplate(
			key="tissue",
			item_code="TDM-SWS-V1-TISSUE",
			item_name="测试抽纸",
			stock_uom="Nos",
			opening_qty=300,
			standard_rate=18,
			uom_conversions=(("Nos", 1), ("Box", 20)),
			wholesale_default_uom="Box",
			retail_default_uom="Nos",
		),
	),
	customers=(
		PartyTemplate(key="retail", name="TDM 测试客户-零售门店"),
		PartyTemplate(key="wholesale", name="TDM 测试客户-批发商"),
		PartyTemplate(key="credit", name="TDM 测试客户-账期客户"),
		PartyTemplate(key="partial", name="TDM 测试客户-部分履约"),
	),
	suppliers=(
		PartyTemplate(key="local", name="TDM 测试供应商-本地"),
		PartyTemplate(key="credit", name="TDM 测试供应商-账期"),
		PartyTemplate(key="partial", name="TDM 测试供应商-部分付款"),
	),
	scenarios=(
		ScenarioTemplate("sales-open", "sales", "order_only", "retail", "tissue", 8, "Nos", 22, -35),
		ScenarioTemplate(
			"sales-partial-delivery", "sales", "partial_delivery", "partial", "rice", 10, "Nos", 75, -21,
			partial_qty=4,
		),
		ScenarioTemplate("sales-unpaid", "sales", "unpaid_invoice", "credit", "oil", 6, "Nos", 105, -14),
		ScenarioTemplate(
			"sales-paid", "sales", "paid_invoice", "retail", "water", 2, "Box", 78, -7,
			payment_ratio=1,
		),
		ScenarioTemplate(
			"sales-complete", "sales", "complete", "wholesale", "rice", 2, "Box", 820, -2,
			payment_ratio=1,
		),
		ScenarioTemplate("purchase-open", "purchase", "order_only", "local", "oil", 5, "Box", 480, -30),
		ScenarioTemplate("purchase-received", "purchase", "received", "credit", "water", 8, "Box", 52, -18),
		ScenarioTemplate(
			"purchase-partial-paid", "purchase", "partial_paid", "partial", "tissue", 4, "Box", 260, -9,
			payment_ratio=0.5,
		),
	),
)


DATASETS = {STANDARD_WHOLESALE_SMALL_V1.code: STANDARD_WHOLESALE_SMALL_V1}

SCALE_PROFILES = {
	"small": 1,
	"medium": 5,
	"large": 20,
}
MAX_SCENARIO_COPIES = max(SCALE_PROFILES.values())


def normalize_scale(value: str | None, *, default: str = "small") -> tuple[str, int]:
	profile = str(value or default).strip().lower()
	if profile not in SCALE_PROFILES:
		raise ValueError(f"未知数据量档位：{value}。仅支持 small、medium、large。")
	copies = min(SCALE_PROFILES[profile], MAX_SCENARIO_COPIES)
	return profile, copies


def get_dataset(code: str) -> DatasetDefinition:
	try:
		return DATASETS[(code or "").strip()]
	except KeyError as exc:
		raise ValueError(f"未知测试数据集：{code}") from exc


def list_datasets() -> list[dict]:
	return [dataset.serialize() for dataset in DATASETS.values()]
