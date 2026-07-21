from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.background_jobs import get_redis_conn

from erpnext.setup.doctype.transaction_deletion_record.transaction_deletion_record import (
	get_doctypes_to_be_ignored,
	get_protected_doctypes,
)
from myapp.test_data.registry import find_open_run, list_active_objects
from myapp.test_data.safety import ALLOWED_ENVIRONMENTS, get_environment_type, parse_allowed_companies
from myapp.test_data.service import require_test_data_manager


TASK_STATUS_FIELDS = (
	"delete_bin_data_status",
	"delete_leads_and_addresses_status",
	"reset_company_default_values_status",
	"clear_notifications_status",
	"initialize_doctypes_table_status",
	"delete_transactions_status",
)


def expected_company_reset_confirmation(company: str) -> str:
	return f"DELETE ALL TRANSACTIONS {company}"


def get_company_reset_safety_snapshot() -> dict:
	return {
		"enabled": bool(cint(frappe.conf.get("myapp_company_transaction_reset_enabled") or 0)),
		"environment_type": get_environment_type(),
		"allowed_companies": list(
			parse_allowed_companies(
				frappe.conf.get("myapp_company_transaction_reset_allowed_companies")
			)
		),
	}


def _get_running_deletion_record() -> str | None:
	return frappe.db.get_value(
		"Transaction Deletion Record",
		{"docstatus": 1, "status": ("in", ["Running", "Queued"])},
		"name",
	)


def _build_company_deletion_plan(company: str) -> list[dict]:
	ignored = set(get_doctypes_to_be_ignored()) | set(get_protected_doctypes())
	company_fields = frappe.get_all(
		"DocField",
		filters={"fieldtype": "Link", "options": "Company"},
		fields=["parent", "fieldname"],
		order_by="parent asc, idx asc",
	)
	plan = []
	seen = set()
	for row in company_fields:
		key = (row.parent, row.fieldname)
		if key in seen or row.parent in ignored:
			continue
		seen.add(key)
		meta = frappe.db.get_value("DocType", row.parent, ["istable", "is_virtual"], as_dict=True)
		if not meta or meta.istable or meta.is_virtual:
			continue
		count = int(frappe.db.count(row.parent, {row.fieldname: company}) or 0)
		if count:
			plan.append(
				{
					"doctype": row.parent,
					"company_field": row.fieldname,
					"document_count": count,
				}
			)
	return sorted(plan, key=lambda item: (-item["document_count"], item["doctype"], item["company_field"]))


def preview_company_transaction_reset(*, company: str) -> dict:
	require_test_data_manager()
	safety = get_company_reset_safety_snapshot()
	blockers = []
	if not safety["enabled"]:
		blockers.append("myapp_company_transaction_reset_enabled 未启用。")
	if safety["environment_type"] not in ALLOWED_ENVIRONMENTS:
		blockers.append("当前环境类型不允许执行公司级交易重置。")
	if company not in safety["allowed_companies"]:
		blockers.append(f"公司 {company} 不在公司级交易重置白名单中。")
	if not frappe.db.exists("Company", company):
		blockers.append(f"公司 {company} 不存在。")
	if open_run := find_open_run(company):
		blockers.append(f"公司已有测试数据任务 {open_run.name} 正在执行。")
	if running_record := _get_running_deletion_record():
		blockers.append(f"系统已有交易删除任务 {running_record} 正在执行。")

	plan = _build_company_deletion_plan(company) if frappe.db.exists("Company", company) else []
	total_references = sum(row["document_count"] for row in plan)
	active_template_objects = list_active_objects(company=company)
	return {
		"status": "success",
		"data": {
			"allowed": not blockers,
			"company": company,
			"safety": safety,
			"blockers": blockers,
			"confirmation_text": expected_company_reset_confirmation(company),
			"doctype_count": len(plan),
			"estimated_document_references": total_references,
			"active_template_object_count": len(active_template_objects),
			"plan": plan,
			"retained_master_doctypes": get_doctypes_to_be_ignored(),
		},
	}


def _serialize_deletion_record(doc) -> dict:
	task_statuses = {field: getattr(doc, field, None) for field in TASK_STATUS_FIELDS}
	to_delete = [
		{
			"doctype": row.doctype_name,
			"company_field": row.company_field,
			"document_count": int(row.document_count or 0),
			"deleted": bool(row.deleted),
		}
		for row in doc.doctypes_to_delete
		if int(row.document_count or 0) > 0
	]
	processed = sum(int(row.no_of_docs or 0) for row in doc.doctypes)
	total = sum(row["document_count"] for row in to_delete)
	if doc.status == "Completed":
		processed = total
	return {
		"name": doc.name,
		"company": doc.company,
		"status": doc.status or "Queued",
		"owner": doc.owner,
		"creation": doc.creation,
		"modified": doc.modified,
		"error": doc.error_log,
		"task_statuses": task_statuses,
		"progress": {"processed": processed, "total": total},
		"to_delete": sorted(
			to_delete,
			key=lambda item: (-item["document_count"], item["doctype"], item["company_field"] or ""),
		),
		"active_template_object_count": len(list_active_objects(company=doc.company)),
	}


def request_company_transaction_reset(
	*,
	company: str,
	confirmation_text: str,
	acknowledge_irreversible: int | bool = 0,
) -> dict:
	require_test_data_manager()
	preview = preview_company_transaction_reset(company=company)["data"]
	if not preview["allowed"]:
		frappe.throw(_("公司级交易重置预检未通过：{0}").format("；".join(preview["blockers"])))
	if (confirmation_text or "").strip() != preview["confirmation_text"]:
		frappe.throw(_("确认文本不正确，请输入：{0}").format(preview["confirmation_text"]))
	if not cint(acknowledge_irreversible):
		frappe.throw(_("必须明确确认该操作不可逆，并已准备必要备份。"))

	lock = get_redis_conn().lock(
		f"myapp:company-transaction-reset-request:{frappe.local.site}",
		timeout=60,
		blocking_timeout=2,
	)
	if not lock.acquire(blocking=True):
		frappe.throw(_("公司级交易重置请求正在处理中，请稍后重试。"))
	try:
		if running_record := _get_running_deletion_record():
			frappe.throw(_("系统已有交易删除任务 {0} 正在执行。").format(running_record))
		doc = frappe.get_doc({"doctype": "Transaction Deletion Record", "company": company})
		doc.insert()
		doc.generate_to_delete_list()
		doc.reload()
		doc.submit()
		frappe.db.commit()
		return {
			"status": "success",
			"message": _("公司级交易重置任务已创建。"),
			"data": {"record": _serialize_deletion_record(doc), "preview": preview},
		}
	finally:
		if lock.owned():
			lock.release()


def get_company_transaction_reset(record_name: str) -> dict:
	require_test_data_manager()
	doc = frappe.get_doc("Transaction Deletion Record", record_name)
	doc.check_permission("read")
	return {"status": "success", "data": _serialize_deletion_record(doc)}
