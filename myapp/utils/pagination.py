from __future__ import annotations

from frappe.utils import cint


def build_offset_pagination(*, start: int, limit: int, total_count: int, row_count: int):
	start = max(0, cint(start))
	limit = max(1, cint(limit))
	total_count = max(0, cint(total_count))
	row_count = max(0, cint(row_count))
	page = start // limit + 1

	return {
		"page": page,
		"page_size": limit,
		"start": start,
		"limit": limit,
		"total_count": total_count,
		"has_more": start + row_count < total_count,
	}


def build_page_pagination(*, page: int, page_size: int, total_count: int, row_count: int):
	page = max(1, cint(page))
	page_size = max(1, cint(page_size))
	total_count = max(0, cint(total_count))
	row_count = max(0, cint(row_count))
	start = (page - 1) * page_size

	return {
		"page": page,
		"page_size": page_size,
		"start": start,
		"limit": page_size,
		"total_count": total_count,
		"has_more": start + row_count < total_count,
	}
