import frappe


@frappe.whitelist(allow_guest=True)
def test_remote_debug():
	# 👆 删除了 import pydevd_pycharm 和 settrace

	# 👇 你只需要在这里点一个红色的断点
	welcome_message = "太棒了！你的 VS Code 原生调试彻底打通了！"

	a = 10
	b = 24
	result = a + b

	# 这里的 print 信息会直接显示在 VS Code 下方的“调试控制台”里
	print(f"=== 拦截成功！计算结果是: {result} ===")

	return {"status": "success", "message": welcome_message, "magic_number": result}
