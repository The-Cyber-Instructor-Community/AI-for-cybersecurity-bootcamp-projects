# Contracts

This folder defines the shared format that both tools use to talk to each other.

- `redteam_cli` sends attack attempts using this format.
- `guardian_service` (or any other security filter) receives requests and replies using this same format.

Neither tool needs to know how the other one works internally. They only need to agree on this shared format. That is what makes them swappable: you could replace the Guardian Service with a completely different filter, or point the attack tool at a completely different app, and nothing would break, as long as the new piece still follows this format.

## Files in this folder

- **schemas.py**: the format, written in Python code (used by both tools directly).
- **openapi.yaml**: the same format, written in a standard, language-independent way. Useful if someone wants to build a filter in a different programming language.
- **adapter.py**: lets the attack tool test two different kinds of targets: a live web service, or a Python function running locally.
- **attack_corpus.example.yaml**: an example config file showing how to set up a test.

## Overall

redteam_cli sends requests to guardian_service (or any other filter that speaks the same format).

## Versioning

This is version 1 of the format. If it ever needs a breaking change in the future, I will create version 2 rather than changing version 1, so nothing that already works stops working.