from orchestrator import analyze_binary
from pathlib import Path

tp = 0
fp = 0
tn = 0
fn = 0
import csv

answers = {}
with open("corpus/answer_key.csv") as f:
	reader = csv.DictReader(f)
	for row in reader:
		answers[row["binary"]] = row["vulnerable"]
for name in answers:
	binary = Path("corpus/bin") / name
	if not binary.is_file():
		continue
	name = binary.name
	print(binary.name)
	verdicts = analyze_binary(str(binary))
	print(verdicts)
	print("---")
	tool_says = any(v["vulnerable"] for v in verdicts)
	actual = answers[name] == "1"
	if tool_says and actual:
		tp += 1
	elif tool_says and not actual:
		fp += 1
	elif not tool_says and actual:
		fn += 1
	else:
		tn += 1
print("TP:", tp, "FP:", fp, "TN:", tn, "FN:", fn)
