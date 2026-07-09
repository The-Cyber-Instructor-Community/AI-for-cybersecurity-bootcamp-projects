import re
import json
import ollama

def hex_to_decimal(code):
	def repl(match):
		return str(int(match.group(0), 16))
	return re.sub(r'0x[0-9a-fA-F]+', repl, code)

def extract_analysis_facts(code):
	facts = []

	# Detect scanf width specifier
	m = re.search(
			r'(?:scanf|__isoc23_scanf)\s*\(\s*"%(\d+)s"',
			code
		)

	if m:
		width = int(m.group(1))
		facts.append(f"scanf width specifier = {width}")

	# Detect memcpy constant length
	m_buf = re.search(r'char\s+(\w+)\s*\[(\d+)\]', code)
	m_memcpy = re.search(
				r'memcpy\s*\(\s*(\w+)\s*,\s*[^,]+\s*,\s*(0x[0-9a-fA-F]+|\d+)\)',
				code
			)

	if m_buf and m_memcpy and m_buf.group(1) == m_memcpy.group(1):
		size = int(m_buf.group(2))
		length = int(m_memcpy.group(2), 0)   # Handles both decimal and hex

		facts.extend([
				f"destination buffer size = {size}",
				f"memcpy copy length = {length}",
				"memcpy write is bounded" if length <= size
				else "memcpy write exceeds destination buffer"
			])
	return facts

def analyze_code(decompiled_code):
	prompt = """
You are a security engineer experienced in reverse engineering and stack buffer overflow detection.

Analyze ONLY the decompiled function shown.

Determine:
- destination buffer
- destination buffer size
- input source
- whether the write is bounded
- whether a stack buffer overflow exists

Rules:

- Analyze ONLY the code shown.
- Never invent buffers.
- CPU registers (rsp, rbp, rax, rdi, rsi, rcx, etc.) are never buffers.
- Do NOT analyze vulnerabilities inside functions that are merely called.
- Only report a vulnerability if a fixed-size destination buffer can actually be overflowed.
- Do NOT classify a function as vulnerable based only on its name.
- Always compare the maximum bytes written with the destination buffer size before deciding.

Safe (return vulnerable=false):

- fgets(buf, size, ...) because it reads at most size-1 characters.
- strncpy(dst, src, n) when n <= destination buffer size.
- snprintf(buf, size, ...) when size <= destination buffer size.
- scanf("%Ns", dst):
  - Extract the decimal width N from the format string.
  - Maximum bytes written = N + 1 (including the null terminator).
  - If N + 1 <= destination buffer size, return vulnerable=false.
- memcpy(dst, src, len):
  - len is the exact number of bytes copied.
  - If len <= destination buffer size, return vulnerable=false.

Dangerous (return vulnerable=true):

- gets
- strcpy
- strcat
- sprintf
- scanf("%s") with NO width specifier.
- memcpy only when len > destination buffer size or len is unknown.

If the write is provably bounded by the destination buffer, return vulnerable=false.

Answer ONLY with a JSON object containing exactly these fields:

vulnerable
buffer
buffer_size
input_source
reason
fix
likelihood

Requirements:

- buffer_size must be a decimal integer.
- Output exactly one valid JSON object.
- No markdown.
- No comments.
- No explanations outside the JSON.

Example:
{"vulnerable": true, "buffer": "buf", "buffer_size": 64, "input_source": "argv", "reason": "...", "fix": "...", "likelihood": 0.9}
"""
	decompiled_code = hex_to_decimal(decompiled_code)
	facts = extract_analysis_facts(decompiled_code)
	#print("CODE SENT TO LLM")
	#print(decompiled_code)
	#print("-" * 80)

	full_prompt = f"""{prompt}

	==========================
	DECOMPILED FUNCTION
	==========================

	{decompiled_code}
	"""

	# Add recovered facts if any
	if facts:
		full_prompt += "\nRecovered facts:\n"
		for fact in facts:
			full_prompt += f"- {fact}\n"

	full_prompt += """

	==========================
	Return ONLY the JSON object.
	==========================
	"""
	#print(facts)
	#print(full_prompt)
	response = ollama.generate(model="llama3.1:8b", prompt=full_prompt, options={"temperature": 0})
	raw = response["response"]
	#print("RAW RESPONSE")
	#print(raw)
	#print("-" * 80)
	# extract the JSON object: everything between the first { and the last }
	if "{" in raw and "}" in raw:
		raw = raw[raw.index("{"): raw.rindex("}") + 1]
	try:
		return json.loads(raw)
	except:
		return {"vulnerable": None, "error": "could not parse", "raw": raw}

if __name__ == "__main__":
	import sys
	sys.path.insert(0, "src")
	from r2_driver import R2Driver

	#print("safe04_scanfw")
	d = R2Driver("corpus/bin/safe05_memcpy")
	d.open()
	code = d.get_decompiled("dbg.load")
	d.close()

	verdict = analyze_code(code)
	print(verdict)

