from graven_voice import print_verdicts
from pathlib import Path
from orchestrator import analyze_binary
import subprocess
import re

def fix_and_verify(binary_path, source_path=None):
	# binary_path: full path to the binary (wherever it is)
	# source_path: full path to source, OR None to auto-guess
	if source_path is None:
		# auto-guess: source is binary path + ".c"
		source_path = binary_path + ".c"

	# Step 1: analyze the original binary
	print("=== ANALYZING ORIGINAL ===")
	before = analyze_binary(binary_path)
	print_verdicts(before)

	# is it vulnerable?
	is_vuln = any(v.get("vulnerable") for v in before)
	if not is_vuln:
		print("No vulnerability found - nothing to fix.")
		return False

	# do we have source to fix?
	if not Path(source_path).is_file():
		print("Vulnerability found, but no source available - cannot auto-fix.")
		return True

	print("Source found - applying fix...")
	# Step 2: read the source, apply the fix, write fixed source
	with open(source_path) as f:
		original_code = f.read()
	fixed_code = apply_fix(original_code)

	fixed_source = source_path.replace(".c", "_fixed.c")
	with open(fixed_source, "w") as f:
		f.write(fixed_code)
	print("Fixed source written:", fixed_source)

	# Step 3: recompile the fixed source
	fixed_binary = binary_path + "_fixed"
	compile_result = subprocess.run(
						["gcc", "-fno-stack-protector", "-no-pie", "-g", "-w",
						"-include", "stdio.h", "-include", "string.h",
						"-o", fixed_binary, fixed_source],
						capture_output=True, text=True
				)
	if compile_result.returncode != 0:
		print("Recompile failed:", compile_result.stderr)
		return True
	print("Recompiled successfully:", fixed_binary)

	# Step 4: re-analyze the fixed binary
	print("=== ANALYZING FIXED ===")
	after = analyze_binary(fixed_binary)
	print_verdicts(after)

	# Step 5: show the result
	still_vuln = any(v.get("vulnerable") for v in after)
	if still_vuln:
		print("Fix did NOT resolve the vulnerability.")
		return True 
	else:
		print("VERIFIED: vulnerability resolved. Found -> Fixed -> Proven.")
		return True 


def apply_fix(code):
	# strcpy(dst, src) -> strncpy(dst, src, sizeof(dst)-1)
	code = re.sub(
			r'strcpy\s*\(\s*(\w+)\s*,\s*([^)]+)\)',
			r'strncpy(\1, \2, sizeof(\1)-1)',
			code
		)
	# gets(buf) -> fgets(buf, sizeof(buf), stdin)
	code = re.sub(
			r'gets\s*\(\s*(\w+)\s*\)',
			r'fgets(\1, sizeof(\1), stdin)',
			code
		)
	# sprintf(buf, ...) -> snprintf(buf, sizeof(buf), ...)
	code = re.sub(
			r'sprintf\s*\(\s*(\w+)\s*,',
			r'snprintf(\1, sizeof(\1),',
			code
		)
	# strcat(dst, src) -> strncat(dst, src, sizeof(dst)-strlen(dst)-1)
	code = re.sub(
			r'strcat\s*\(\s*(\w+)\s*,\s*([^)]+)\)',
			r'strncat(\1, \2, sizeof(\1)-strlen(\1)-1)',
			code
		)
	# scanf("%s", buf) -> scanf("%Ns", buf) using buffer size
	# simplest safe fix: replace %s with a bounded read via fgets
	code = re.sub(
			r'scanf\s*\(\s*"%s"\s*,\s*(\w+)\s*\)',
			r'fgets(\1, sizeof(\1), stdin)',
			code
		)
	# memcpy(dst, src, len) -> memcpy(dst, src, sizeof(dst)) when len too big
	code = re.sub(
			r'memcpy\s*\(\s*(\w+)\s*,\s*([^,]+),\s*[^)]+\)',
			r'memcpy(\1, \2, sizeof(\1))',
			code
		)
	return code

if __name__ == "__main__":
	from graven_voice import greeting, signoff
	greeting()
	fix_and_verify("corpus/bin/vuln01_strcpy", "corpus/vuln01_strcpy.c")
	signoff(1, 1)
