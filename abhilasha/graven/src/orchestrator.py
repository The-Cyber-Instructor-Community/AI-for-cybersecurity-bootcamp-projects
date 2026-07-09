from r2_driver import R2Driver, DANGEROUS
from llm import analyze_code

def analyze_binary(binary_path):
	d = R2Driver(binary_path)
	d.open()
	func_list = d.get_user_functions()
	result = []
	for f in func_list:
		code = d.get_decompiled(f["name"])
		if any(danger in code for danger in DANGEROUS):
			verdict = analyze_code(code)
			result.append(verdict)
	d.close()
	if not result:
		return [{"vulnerable": False, "reason": "no dangerous functions found in this binary"}]
	return result

if __name__ == "__main__":
	results = analyze_binary("vuln01")
	for r in results:
		print(r)
		print("---")
