"""Opt-in read-only row-lock check using two local MariaDB connections."""

import os
from unittest import TestCase, skipUnless

import frappe

from myapp.services import ai_repository


@skipUnless(os.getenv("MYAPP_AI_DRAFT_LOCK_TEST_SITE"), "Requires explicit local lock-test site")
class AiDraftLockTests(TestCase):
	def test_execution_lock_survives_repository_return_until_transaction_end(self):
		frappe.init(site=os.environ["MYAPP_AI_DRAFT_LOCK_TEST_SITE"], sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		other = None
		try:
			rows = frappe.db.sql("SELECT name, owner FROM `tabMyApp AI Draft` ORDER BY creation LIMIT 1", as_dict=True)
			if not rows:
				self.skipTest("Requires an existing draft; this test never creates business data")
			row = rows[0]
			ai_repository.get_draft(draft_id=row.name, user=row.owner, for_update=True)
			other = frappe.db.get_connection()
			cursor = other.cursor()
			cursor.execute("SET SESSION innodb_lock_wait_timeout=1")
			query = "SELECT name FROM `tabMyApp AI Draft` WHERE name=%s AND owner=%s FOR UPDATE"
			try:
				cursor.execute(query, (row.name, row.owner))
			except Exception as error:
				self.assertEqual(error.args[0], 1205, "Expected lock wait timeout")
			else:
				self.fail("The execution read did not keep a transaction-scoped row lock")
			other.rollback()
			frappe.db.rollback()
			cursor.execute(query, (row.name, row.owner))
			self.assertEqual(len(cursor.fetchall()), 1)
		finally:
			if other:
				other.rollback()
				other.close()
			frappe.db.rollback()
			frappe.destroy()
