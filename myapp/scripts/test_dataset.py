from __future__ import annotations

import argparse
import json
import os

import frappe

from myapp.test_data.runner import execute_run
from myapp.test_data.company_reset import (
	get_company_transaction_reset,
	preview_company_transaction_reset,
	request_company_transaction_reset,
)
from myapp.test_data.safety import expected_confirmation
from myapp.test_data.service import (
	get_dataset_run,
	list_test_datasets,
	preview_dataset,
	request_dataset_run,
	validate_latest_dataset,
)


def _print(value) -> None:
	print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="MyApp enterprise test dataset management CLI.")
	parser.add_argument("--site", default="localhost")
	parser.add_argument("--sites-path", default="/home/frappe/frappe-bench/sites")
	subparsers = parser.add_subparsers(dest="command", required=True)
	subparsers.add_parser("catalog")

	for command in ("preview", "generate", "reset", "supplement"):
		subparser = subparsers.add_parser(command)
		subparser.add_argument("--dataset", default="standard-wholesale-small")
		subparser.add_argument("--company", required=True)
		subparser.add_argument("--warehouse", required=True)
		subparser.add_argument("--base-date")
		subparser.add_argument("--seed", type=int, default=1)
		subparser.add_argument("--scale", choices=("small", "medium", "large"), default="small")
		if command in {"preview", "supplement"}:
			subparser.add_argument("--scenario", action="append", dest="scenario_keys")
		if command == "preview":
			subparser.add_argument(
				"--action", choices=("generate", "reset", "supplement"), default="generate"
			)
		if command in {"generate", "reset", "supplement"}:
			subparser.add_argument("--enqueue", action="store_true")

	status_parser = subparsers.add_parser("status")
	status_parser.add_argument("--run", required=True)
	validate_parser = subparsers.add_parser("validate")
	validate_parser.add_argument("--dataset", default="standard-wholesale-small")
	validate_parser.add_argument("--company", required=True)
	company_reset_preview = subparsers.add_parser("company-reset-preview")
	company_reset_preview.add_argument("--company", required=True)
	company_reset = subparsers.add_parser("company-reset")
	company_reset.add_argument("--company", required=True)
	company_reset.add_argument("--confirmation", required=True)
	company_reset.add_argument("--acknowledge-irreversible", action="store_true")
	company_reset_status = subparsers.add_parser("company-reset-status")
	company_reset_status.add_argument("--record", required=True)
	return parser


def main() -> None:
	args = _parser().parse_args()
	sites_path = os.path.abspath(args.sites_path)
	os.chdir(sites_path)
	frappe.init(site=args.site, sites_path=sites_path)
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		if args.command == "catalog":
			result = list_test_datasets()
		elif args.command == "preview":
			result = preview_dataset(
				dataset_code=args.dataset,
				company=args.company,
				warehouse=args.warehouse,
				action=args.action,
				base_date=args.base_date,
				seed=args.seed,
				scenario_keys=args.scenario_keys,
				scale=args.scale,
			)
		elif args.command in {"generate", "reset", "supplement"}:
			request = request_dataset_run(
				dataset_code=args.dataset,
				company=args.company,
				warehouse=args.warehouse,
				action=args.command,
				confirmation_text=expected_confirmation(args.command, args.company),
				base_date=args.base_date,
				seed=args.seed,
				scenario_keys=getattr(args, "scenario_keys", None),
				scale=args.scale,
				enqueue=args.enqueue,
			)
			run_name = request["data"]["run_name"]
			if args.enqueue:
				frappe.db.commit()
				result = request
			else:
				result = {"request": request, "execution": execute_run(run_name)}
		elif args.command == "status":
			result = get_dataset_run(args.run)
		elif args.command == "company-reset-preview":
			result = preview_company_transaction_reset(company=args.company)
		elif args.command == "company-reset":
			result = request_company_transaction_reset(
				company=args.company,
				confirmation_text=args.confirmation,
				acknowledge_irreversible=args.acknowledge_irreversible,
			)
		elif args.command == "company-reset-status":
			result = get_company_transaction_reset(args.record)
		else:
			result = validate_latest_dataset(args.company, args.dataset)
		_print(result)
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
