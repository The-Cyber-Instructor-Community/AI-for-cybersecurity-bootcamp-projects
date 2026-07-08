import subprocess, sys, time

def show_owl():
	# call chafa to render the owl in the terminal
	subprocess.run(["chafa", "owl_cropped.png", "--size", "30x30"])

def typewriter(text, delay=0.03, color="\033[33m"):  # amber to match the owl
	reset = "\033[0m"
	sys.stdout.write(color)
	for ch in text:
		sys.stdout.write(ch); sys.stdout.flush(); time.sleep(delay)
	sys.stdout.write(reset + "\n")

def greeting():
	show_owl()
	typewriter("G R A V E N", color="\033[97m")
	typewriter("No source. No tales. No secrets I can't exhume.", color="\033[33m")
	print()

def print_verdicts(result, had_source=True):
	vulns = [r for r in result if r.get("vulnerable")]

	print()
	if not had_source:
		print("\033[90mno source to raise. i read the bones as they lie.\033[0m")
	print()

	if not vulns:
		print("\033[32m  nothing buried here. the binary rests clean.\033[0m")
		print()
		return

	for r in vulns:
		print(f"\033[31m  ✦ WOUND FOUND\033[0m  buffer '{r.get('buffer')}' ({r.get('buffer_size')} bytes)")
		print(f"      {r.get('reason')}")
		print(f"      \033[33mremedy:\033[0m {r.get('fix')}")
		print()

	safe_count = len(result) - len(vulns)
	if safe_count > 0:
		print(f"\033[90m  {safe_count} other function(s) examined, nothing hidden.\033[0m")
		print()

def signoff(total, found):
	typewriter(f"graven :: {total} examined. {found} were hiding something. they always are.", color="\033[33m")


if __name__ == "__main__":
	greeting()
