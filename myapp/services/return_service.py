import frappe
from frappe import _
from frappe.utils import flt

_SOURCE_META = {
    "Delivery Note": {
        "business_type": "sales",
        "source_label": "销售发货单",
        "detail_name_key": "delivery_note_item",
        "detail_submit_key": "delivery_note_item",
        "detail_loader_path": "myapp.services.order_service.get_delivery_note_detail",
        "loader_kwarg": "delivery_note_name",
    },
    "Sales Invoice": {
        "business_type": "sales",
        "source_label": "销售发票",
        "detail_name_key": "sales_invoice_item",
        "detail_submit_key": "sales_invoice_item",
        "detail_loader_path": "myapp.services.order_service.get_sales_invoice_detail",
        "loader_kwarg": "sales_invoice_name",
    },
    "Purchase Receipt": {
        "business_type": "purchase",
        "source_label": "采购收货单",
        "detail_name_key": "purchase_receipt_item",
        "detail_submit_key": "purchase_receipt_item",
        "detail_loader_path": "myapp.services.purchase_service.get_purchase_receipt_detail_v2",
        "loader_kwarg": "receipt_name",
    },
    "Purchase Invoice": {
        "business_type": "purchase",
        "source_label": "采购发票",
        "detail_name_key": "purchase_invoice_item",
        "detail_submit_key": "purchase_invoice_item",
        "detail_loader_path": "myapp.services.purchase_service.get_purchase_invoice_detail_v2",
        "loader_kwarg": "invoice_name",
    },
}


def _normalize_text(value):
    return (value or "").strip() if isinstance(value, str) else value


def _get_detail_loader(loader_path: str):
    return frappe.get_attr(loader_path)


def _document_status_label(docstatus: int):
    if int(docstatus or 0) == 2:
        return "cancelled"
    if int(docstatus or 0) == 1:
        return "submitted"
    return "draft"


def _map_party(detail_data: dict, business_type: str):
    if business_type == "sales":
        customer = detail_data.get("customer") or {}
        return {
            "party_type": "Customer",
            "party_name": customer.get("name"),
            "display_name": customer.get("display_name") or customer.get("name"),
            "contact_person": customer.get("contact_person"),
            "contact_display_name": customer.get("contact_display_name"),
            "contact_phone": customer.get("contact_phone"),
            "contact_email": customer.get("contact_email"),
        }

    supplier = detail_data.get("supplier") or {}
    return {
        "party_type": "Supplier",
        "party_name": supplier.get("name"),
        "display_name": supplier.get("display_name") or supplier.get("name"),
        "contact_person": supplier.get("contact_person"),
        "contact_display_name": supplier.get("contact_display_name"),
        "contact_phone": supplier.get("contact_phone"),
        "contact_email": supplier.get("contact_email"),
    }


def _map_item_rows(items: list[dict], *, detail_name_key: str):
    mapped_rows = []
    for item in items or []:
        source_qty = abs(flt(item.get("qty") or 0))
        mapped_rows.append(
            {
                "detail_id": item.get(detail_name_key),
                "detail_submit_key": detail_name_key,
                "item_code": item.get("item_code"),
                "item_name": item.get("item_name"),
                "uom": item.get("uom"),
                "warehouse": item.get("warehouse"),
                "rate": flt(item.get("rate") or 0),
                "amount": flt(item.get("amount") or 0),
                "source_qty": source_qty,
                "returned_qty": 0,
                "max_returnable_qty": source_qty,
                "default_return_qty": source_qty,
                "source_row": item,
            }
        )
    return mapped_rows


def _collect_return_references(return_doc):
    references = {
        "sales_orders": [],
        "delivery_notes": [],
        "sales_invoices": [],
        "purchase_orders": [],
        "purchase_receipts": [],
        "purchase_invoices": [],
    }

    for item in getattr(return_doc, "items", None) or []:
        pairs = (
            ("sales_orders", getattr(item, "sales_order", None) or getattr(item, "against_sales_order", None)),
            ("delivery_notes", getattr(item, "delivery_note", None)),
            ("sales_invoices", getattr(item, "sales_invoice", None)),
            ("purchase_orders", getattr(item, "purchase_order", None)),
            ("purchase_receipts", getattr(item, "purchase_receipt", None)),
            ("purchase_invoices", getattr(item, "purchase_invoice", None)),
        )
        for bucket, value in pairs:
            if value and value not in references[bucket]:
                references[bucket].append(value)

    return references


def build_return_submission_payload(return_doc, *, source_doctype: str, source_name: str, business_type: str, is_partial_return: bool):
    total_qty = 0.0
    total_amount = 0.0
    item_count = 0
    for item in getattr(return_doc, "items", None) or []:
        total_qty += abs(flt(getattr(item, "qty", 0) or 0))
        amount = getattr(item, "amount", None)
        if amount is None:
            amount = flt(getattr(item, "rate", 0) or 0) * flt(getattr(item, "qty", 0) or 0)
        total_amount += abs(flt(amount or 0))
        item_count += 1

    suggested_next_action = "view_return_document"
    if business_type == "sales" and source_doctype == "Sales Invoice":
        suggested_next_action = "review_refund"
    elif business_type == "purchase" and source_doctype == "Purchase Invoice":
        suggested_next_action = "review_supplier_refund"

    return {
        "status": "success",
        "return_document": return_doc.name,
        "return_doctype": return_doc.doctype,
        "document_status": _document_status_label(getattr(return_doc, "docstatus", 1)),
        "source_doctype": source_doctype,
        "source_name": source_name,
        "business_type": business_type,
        "summary": {
            "item_count": item_count,
            "total_qty": total_qty,
            "return_amount_estimate": total_amount,
            "is_partial_return": bool(is_partial_return),
        },
        "references": _collect_return_references(return_doc),
        "next_actions": {
            "can_view_return_document": True,
            "can_back_to_source": True,
            "suggested_next_action": suggested_next_action,
        },
        "message": _("退货单 {0} 已创建并提交。").format(return_doc.name),
    }


def _resolve_primary_amount(detail_data: dict, source_doctype: str):
    amounts = detail_data.get("amounts") or {}
    if source_doctype == "Delivery Note":
        return flt(amounts.get("delivery_amount_estimate") or 0)
    if source_doctype == "Sales Invoice":
        return flt(amounts.get("invoice_amount_estimate") or 0)
    if source_doctype == "Purchase Receipt":
        return flt(amounts.get("receipt_amount_estimate") or 0)
    return flt(amounts.get("invoice_amount_estimate") or 0)


def _resolve_can_process_return(detail_data: dict, source_doctype: str):
    actions = detail_data.get("actions") or {}
    if source_doctype == "Delivery Note":
        return bool(actions.get("can_cancel_delivery_note", False))
    if source_doctype == "Sales Invoice":
        return bool(actions.get("can_cancel_sales_invoice", False))
    if source_doctype == "Purchase Receipt":
        return bool(actions.get("can_cancel_purchase_receipt", False))
    return bool(actions.get("can_cancel_purchase_invoice", False))


def get_return_source_context_v2(source_doctype: str, source_name: str):
    source_doctype = _normalize_text(source_doctype)
    source_name = _normalize_text(source_name)
    if not source_doctype or not source_name:
        frappe.throw(_("source_doctype 和 source_name 不能为空。"))

    source_meta = _SOURCE_META.get(source_doctype)
    if not source_meta:
        frappe.throw(_("暂不支持对 {0} 获取退货上下文。").format(source_doctype))

    detail_loader = _get_detail_loader(source_meta["detail_loader_path"])
    detail_result = detail_loader(**{source_meta["loader_kwarg"]: source_name})
    detail_data = detail_result.get("data") or {}
    business_type = source_meta["business_type"]

    return {
        "status": "success",
        "data": {
            "business_type": business_type,
            "source_doctype": source_doctype,
            "source_name": source_name,
            "source_label": source_meta["source_label"],
            "document_status": detail_data.get("document_status"),
            "party": _map_party(detail_data, business_type),
            "amounts": {
                **(detail_data.get("amounts") or {}),
                "primary_amount": _resolve_primary_amount(detail_data, source_doctype),
            },
            "actions": {
                "can_process_return": _resolve_can_process_return(detail_data, source_doctype),
                "supports_partial_return": True,
                "detail_submit_key": source_meta["detail_submit_key"],
            },
            "references": detail_data.get("references") or {},
            "meta": {
                **(detail_data.get("meta") or {}),
                "company": (detail_data.get("meta") or {}).get("company"),
                "currency": (detail_data.get("meta") or {}).get("currency"),
            },
            "items": _map_item_rows(
                detail_data.get("items") or [],
                detail_name_key=source_meta["detail_name_key"],
            ),
        },
        "message": _("退货来源单据 {0} 上下文获取成功。").format(source_name),
    }
