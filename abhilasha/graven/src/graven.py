import sys, os
sys.path.insert(0, "src")
from graven_voice import greeting, signoff, print_verdicts
from fix_verify import fix_and_verify
from orchestrator import analyze_binary

def resolve(name):
	# if it's already a real path, use it
	if os.path.isfile(name):
		return name
	# try common locations
	for prefix in ["corpus/bin/", "", "/tmp/owj/code/"]:
		candidate = prefix + name
		if os.path.isfile(candidate):
			return candidate
	return None

def resolve_source(binary_path, name):
	# look for matching .c source
	for candidate in [binary_path + ".c", "corpus/" + os.path.basename(name) + ".c"]:
		if os.path.isfile(candidate):
			return candidate
	return None

if __name__ == "__main__":
	greeting()
	count = 0
	found = 0
	print("\033[33mgraven :: name a binary to exhume, or 'exit' to rest.\033[0m")
	while True:
		line = input("\033[33mgraven> \033[0m").strip()
		if line in ("exit", "quit", "q"):
			break
		if not line:
			continue
		parts = line.split()
		binary = resolve(parts[0])
		if binary is None:
			print(f"graven :: i cannot find '{parts[0]}'. it hides well, or does not exist.")
			continue
		# auto-find source if not given
		source = parts[1] if len(parts) > 1 else resolve_source(binary, parts[0])
		count += 1
		if source and os.path.isfile(source):
			was_vuln = fix_and_verify(binary, source)
			if was_vuln:
				found += 1
		else:
			result = analyze_binary(binary)
			print_verdicts(result, had_source=False)
			if any(v.get("vulnerable") for v in result):
				found += 1

		print("\033[33mgraven :: another binary to exhume, or 'exit' to rest?\033[0m")
	signoff(count, found)
