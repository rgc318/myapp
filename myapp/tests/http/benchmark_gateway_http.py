import argparse
import json
import pathlib
import statistics
import time

from apps.myapp.myapp.tests.http.test_gateway_http import PURCHASE_COMPANY
from apps.myapp.myapp.tests.http.test_gateway_http import SALES_COMPANY
from apps.myapp.myapp.tests.http.test_gateway_http import SALES_ITEM_CODE
from apps.myapp.myapp.tests.http.test_gateway_http import GatewayHttpTestCase


DEFAULT_OUTPUT_FILE = pathlib.Path(__file__).resolve().parents[3] / "performance-baseline-results.json"


class GatewayBenchmarkClient(GatewayHttpTestCase):
	pass


def _extract_message(payload: dict) -> dict:
	message = payload.get("message")
	if not isinstance(message, dict) or not message.get("ok"):
		raise AssertionError(f"Unexpected gateway payload: {json.dumps(payload, ensure_ascii=False)}")
	return message


def _call(method_path: str, payload: dict) -> dict:
	status_code, response_payload = GatewayBenchmarkClient._post_method(method_path, payload)
	if status_code != 200:
		raise AssertionError(
			f"{method_path} returned HTTP {status_code}: {json.dumps(response_payload, ensure_ascii=False)}"
		)
	return _extract_message(response_payload)


def _sample_call(method_path: str, payload: dict, samples: int) -> dict:
	elapsed_ms = []
	last_message = None

	for _ in range(samples):
		start = time.perf_counter()
		last_message = _call(method_path, payload)
		elapsed_ms.append(round((time.perf_counter() - start) * 1000, 2))

	avg_ms = round(statistics.fmean(elapsed_ms), 2)
	min_ms = round(min(elapsed_ms), 2)
	max_ms = round(max(elapsed_ms), 2)
	p95_ms = round(sorted(elapsed_ms)[max(0, int(len(elapsed_ms) * 0.95) - 1)], 2)

	return {
		"method": method_path,
		"request": payload,
		"samples": elapsed_ms,
		"avg_ms": avg_ms,
		"min_ms": min_ms,
		"max_ms": max_ms,
		"p95_ms": p95_ms,
		"last_code": last_message.get("code") if last_message else None,
		"result_meta": _summarize_message(last_message),
	}


def _summarize_message(message: dict | None) -> dict:
	if not message:
		return {}

	data = message.get("data") or {}
	summary = data.get("summary") if isinstance(data, dict) else None
	items = data.get("items") if isinstance(data, dict) else None

	result = {"message": message.get("message")}
	if isinstance(summary, dict):
		result["summary"] = summary
	if isinstance(items, list):
		result["item_count"] = len(items)
	if isinstance(data, dict) and isinstance(data.get("order_name"), str):
		result["order_name"] = data["order_name"]
	if isinstance(data, dict) and isinstance(data.get("name"), str):
		result["name"] = data["name"]
	return result


def _get_first_sales_order_name() -> str:
	message = _call(
		"myapp.api.gateway.search_sales_orders_v2",
		{"company": SALES_COMPANY, "status_filter": "unfinished", "limit": 1, "start": 0},
	)
	items = (((message.get("data") or {}).get("items")) or [])
	if not items:
		raise AssertionError("No sales orders available for benchmark.")
	return items[0]["order_name"]


def _get_first_purchase_order_name() -> str:
	message = _call(
		"myapp.api.gateway.search_purchase_orders_v2",
		{"company": PURCHASE_COMPANY, "status_filter": "unfinished", "limit": 1, "start": 0},
	)
	items = (((message.get("data") or {}).get("items")) or [])
	if not items:
		raise AssertionError("No purchase orders available for benchmark.")
	first_item = items[0]
	return first_item.get("purchase_order_name") or first_item.get("order_name")


def run_benchmark(*, samples: int, output_file: pathlib.Path) -> dict:
	GatewayBenchmarkClient.setUpClass()
	try:
		sales_order_name = _get_first_sales_order_name()
		purchase_order_name = _get_first_purchase_order_name()

		results = {
			"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
			"samples_per_endpoint": samples,
			"targets": {
				"sales_order_name": sales_order_name,
				"purchase_order_name": purchase_order_name,
				"sales_company": SALES_COMPANY,
				"purchase_company": PURCHASE_COMPANY,
				"product_keyword": SALES_ITEM_CODE,
			},
			"benchmarks": [
				_sample_call(
					"myapp.api.gateway.search_sales_orders_v2",
					{"company": SALES_COMPANY, "status_filter": "unfinished", "limit": 20, "start": 0},
					samples,
				),
				_sample_call(
					"myapp.api.gateway.search_purchase_orders_v2",
					{"company": PURCHASE_COMPANY, "status_filter": "unfinished", "limit": 20, "start": 0},
					samples,
				),
				_sample_call(
					"myapp.api.gateway.get_sales_order_detail",
					{"order_name": sales_order_name},
					samples,
				),
				_sample_call(
					"myapp.api.gateway.get_purchase_order_detail_v2",
					{"order_name": purchase_order_name},
					samples,
				),
				_sample_call(
					"myapp.api.gateway.search_product_v2",
					{"search_key": SALES_ITEM_CODE, "price_list": "Standard Selling", "limit": 20},
					samples,
				),
			],
		}
		output_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
		return results
	finally:
		tear_down = getattr(GatewayBenchmarkClient, "tearDownClass", None)
		if callable(tear_down):
			tear_down()


def main():
	parser = argparse.ArgumentParser(description="Run gateway performance baseline benchmarks.")
	parser.add_argument("--samples", type=int, default=5, help="Number of samples per endpoint.")
	parser.add_argument(
		"--output",
		type=pathlib.Path,
		default=DEFAULT_OUTPUT_FILE,
		help="Where to write the benchmark JSON result.",
	)
	args = parser.parse_args()

	results = run_benchmark(samples=args.samples, output_file=args.output.expanduser())
	print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
