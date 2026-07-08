# Eval results (26 held-out cases, 6 analyst-exception)

Ground-truth distribution: {'ambiguous': 6, 'malicious': 14, 'benign': 6}

| metric | no-RAG | with-RAG | Δ |
|---|---|---|---|
| accuracy | 0.615 | 0.923 | +0.308 |
| malicious_precision | 0.714 | 0.933 | +0.219 |
| malicious_recall | 0.714 | 1.0 | +0.286 |
| malicious_f1 | 0.714 | 0.966 | +0.252 |
| over_trigger_rate | 0.333 | 0.083 | -0.250 |
