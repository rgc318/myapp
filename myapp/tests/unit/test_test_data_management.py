from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import frappe

from myapp.api import test_data_api
from myapp.test_data.catalog import get_dataset, list_datasets, normalize_scale
from myapp.test_data.company_reset import (
	_build_company_deletion_plan,
	_serialize_deletion_record,
	expected_company_reset_confirmation,
)
from myapp.test_data.generator import generate_dataset
from myapp.test_data.runner import _delete_registered_objects, _progress_total
from myapp.test_data.safety import expected_confirmation, parse_allowed_companies
from myapp.test_data.service import _expected_counts, _normalize_scenario_keys


class TestTestDataManagement(TestCase):
	def test_standard_dataset_catalog_is_deterministic_and_covers_core_flows(self):
		dataset = get_dataset("standard-wholesale-small")

		self.assertEqual(dataset.version, "2026.07-v1")
		self.assertEqual(len(dataset.items), 4)
		self.assertEqual(len(dataset.customers), 4)
		self.assertEqual(len(dataset.suppliers), 3)
		self.assertEqual(len(dataset.scenarios), 8)
		self.assertEqual(list_datasets()[0]["code"], dataset.code)
		self.assertEqual(
			{scenario.domain for scenario in dataset.scenarios},
			{"sales", "purchase"},
		)

	def test_expected_counts_include_inventory_sales_purchase_and_payments(self):
		counts = _expected_counts(get_dataset("standard-wholesale-small"))

		self.assertEqual(counts["Item"], 4)
		self.assertEqual(counts["Stock Entry"], 4)
		self.assertEqual(counts["Sales Order"], 5)
		self.assertEqual(counts["Sales Invoice"], 3)
		self.assertEqual(counts["Purchase Order"], 3)
		self.assertEqual(counts["Purchase Receipt"], 2)
		self.assertEqual(counts["Payment Entry"], 3)

	def test_scale_profiles_are_normalized_and_limited_to_twenty_copies(self):
		self.assertEqual(normalize_scale(None), ("small", 1))
		self.assertEqual(normalize_scale("MEDIUM"), ("medium", 5))
		self.assertEqual(normalize_scale("large"), ("large", 20))
		with self.assertRaisesRegex(ValueError, "未知数据量档位"):
			normalize_scale("xlarge")

	def test_company_allowlist_parser_accepts_json_and_csv(self):
		self.assertEqual(parse_allowed_companies('["Demo", "QA"]'), ("Demo", "QA"))
		self.assertEqual(parse_allowed_companies("QA, Demo,QA"), ("Demo", "QA"))
		self.assertEqual(parse_allowed_companies(None), ())

	def test_confirmation_text_is_action_and_company_specific(self):
		self.assertEqual(expected_confirmation("generate", "Demo Co"), "GENERATE Demo Co")
		self.assertEqual(expected_confirmation("reset", "Demo Co"), "RESET Demo Co")
		self.assertEqual(expected_confirmation("supplement", "Demo Co"), "SUPPLEMENT Demo Co")
		self.assertEqual(
			expected_company_reset_confirmation("Demo Co"),
			"DELETE ALL TRANSACTIONS Demo Co",
		)

	@patch("myapp.test_data.company_reset.get_protected_doctypes", return_value=["Company"])
	@patch("myapp.test_data.company_reset.get_doctypes_to_be_ignored", return_value=["Customer"])
	def test_company_reset_plan_only_includes_non_protected_company_transactions(
		self,
		_mock_ignored,
		_mock_protected,
	):
		mock_frappe = Mock()
		mock_frappe.get_all.return_value = [
			SimpleNamespace(parent="Sales Order", fieldname="company"),
			SimpleNamespace(parent="Customer", fieldname="company"),
			SimpleNamespace(parent="Company", fieldname="name"),
		]
		mock_frappe.db.get_value.return_value = SimpleNamespace(istable=0, is_virtual=0)
		mock_frappe.db.count.return_value = 7
		with patch("myapp.test_data.company_reset.frappe", mock_frappe):
			plan = _build_company_deletion_plan("Demo Co")

		self.assertEqual(
			plan,
			[
				{
					"doctype": "Sales Order",
					"company_field": "company",
					"document_count": 7,
				}
			],
		)

	@patch("myapp.test_data.company_reset.list_active_objects", return_value=[])
	def test_completed_company_reset_progress_includes_separately_deleted_bins(self, _mock_objects):
		doc = SimpleNamespace(
			name="TDL0001",
			company="Demo Co",
			status="Completed",
			owner="Administrator",
			creation=None,
			modified=None,
			error_log=None,
			doctypes_to_delete=[
				SimpleNamespace(
					doctype_name="Sales Order",
					company_field="company",
					document_count=5,
					deleted=1,
				),
				SimpleNamespace(
					doctype_name="Bin",
					company_field="company",
					document_count=2,
					deleted=1,
				),
			],
			doctypes=[SimpleNamespace(no_of_docs=5)],
			**{field: "Completed" for field in (
				"delete_bin_data_status",
				"delete_leads_and_addresses_status",
				"reset_company_default_values_status",
				"clear_notifications_status",
				"initialize_doctypes_table_status",
				"delete_transactions_status",
			)},
		)

		result = _serialize_deletion_record(doc)

		self.assertEqual(result["progress"], {"processed": 7, "total": 7})

	def test_supplement_counts_only_include_selected_scenarios(self):
		dataset = get_dataset("standard-wholesale-small")
		selected, unknown = _normalize_scenario_keys(
			dataset,
			["sales-unpaid", "purchase-received", "missing-scenario"],
		)
		counts = _expected_counts(dataset, selected, include_master=False)

		self.assertEqual(selected, ["sales-unpaid", "purchase-received"])
		self.assertEqual(unknown, ["missing-scenario"])
		self.assertEqual(
			counts,
			{
				"Purchase Order": 1,
				"Purchase Receipt": 1,
				"Sales Invoice": 1,
				"Sales Order": 1,
			},
		)

	def test_medium_supplement_multiplies_transaction_counts_only(self):
		counts = _expected_counts(
			get_dataset("standard-wholesale-small"),
			["sales-unpaid"],
			include_master=False,
			scenario_copies=5,
		)

		self.assertEqual(counts, {"Sales Invoice": 5, "Sales Order": 5})

	@patch("myapp.test_data.generator.create_sales_scenario")
	@patch("myapp.test_data.generator.load_existing_master_data")
	def test_generator_creates_unique_shifted_scenario_instances(
		self,
		mock_load_existing_master_data,
		mock_create_sales_scenario,
	):
		result = generate_dataset(
			run_name="TDM-RUN-1",
			company="Demo",
			warehouse="Main - D",
			base_date="2026-07-21",
			dataset=get_dataset("standard-wholesale-small"),
			create_masters=False,
			scenario_keys=["sales-open"],
			scale="medium",
			scenario_copies=5,
		)

		mock_load_existing_master_data.assert_called_once()
		self.assertEqual(mock_create_sales_scenario.call_count, 5)
		self.assertEqual(
			[call_item.kwargs["scenario_key"] for call_item in mock_create_sales_scenario.call_args_list],
			["sales-open#1", "sales-open#2", "sales-open#3", "sales-open#4", "sales-open#5"],
		)
		self.assertEqual(
			[call_item.kwargs["date_shift_days"] for call_item in mock_create_sales_scenario.call_args_list],
			[0, -1, -2, -3, -4],
		)
		self.assertEqual(result["scale"], "medium")
		self.assertEqual(result["scenario_copies"], 5)
		self.assertEqual(result["scenario_instance_count"], 5)

	def test_medium_supplement_progress_has_five_instances_and_validation(self):
		total = _progress_total(
			get_dataset("standard-wholesale-small"),
			action="supplement",
			selected_scenario_count=1,
			scenario_copies=5,
		)

		self.assertEqual(total, 6)

	def test_mutating_test_data_apis_are_post_only(self):
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func.get(test_data_api.request_test_dataset_run_v1),
			["POST"],
		)
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func.get(test_data_api.validate_test_dataset_v1),
			["POST"],
		)
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func.get(
				test_data_api.request_company_transaction_reset_v1
			),
			["POST"],
		)

	@patch("myapp.test_data.runner.mark_object_deleted")
	@patch("myapp.test_data.runner.list_active_objects")
	def test_missing_registered_objects_are_reconciled_during_template_reset(
		self,
		mock_list_active_objects,
		mock_mark_deleted,
	):
		mock_list_active_objects.return_value = [
			SimpleNamespace(name="OBJ-1", doctype_name="Sales Order", document_name="SO-MISSING")
		]
		mock_frappe = Mock()
		mock_frappe.db.exists.return_value = False
		with patch("myapp.test_data.runner.frappe", mock_frappe):
			result = _delete_registered_objects(company="Demo", dataset_code="standard-wholesale-small")

		self.assertEqual(result, {"object_count": 1, "counts": {}})
		mock_mark_deleted.assert_called_once_with("OBJ-1")
		mock_frappe.delete_doc.assert_not_called()

	@patch("myapp.test_data.runner.mark_object_deleted")
	@patch("myapp.test_data.runner.list_active_objects")
	def test_registered_objects_are_cancelled_and_deleted_in_reverse_order(
		self,
		mock_list_active_objects,
		mock_mark_deleted,
	):
		mock_list_active_objects.return_value = [
			SimpleNamespace(name="OBJ-1", doctype_name="Sales Order", document_name="SO-1"),
			SimpleNamespace(name="OBJ-2", doctype_name="Sales Invoice", document_name="SI-1"),
		]
		order_doc = Mock(docstatus=1)
		invoice_doc = Mock(docstatus=1)
		mock_frappe = Mock()
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.side_effect = [invoice_doc, order_doc]
		with patch("myapp.test_data.runner.frappe", mock_frappe):
			result = _delete_registered_objects(company="Demo", dataset_code="standard-wholesale-small")

		self.assertEqual(result["object_count"], 2)
		invoice_doc.cancel.assert_called_once_with()
		order_doc.cancel.assert_called_once_with()
		self.assertEqual(
			mock_frappe.delete_doc.call_args_list,
			[
				call("Sales Invoice", "SI-1", ignore_permissions=True, force=True),
				call("Sales Order", "SO-1", ignore_permissions=True, force=True),
			],
		)
		self.assertEqual(mock_mark_deleted.call_args_list, [call("OBJ-2"), call("OBJ-1")])
