"""
agent/model_analyzer.py
────────────────────────
Uses the fine-tuned Llama 3.1 8B LoRA model to generate deep CVE analysis.

Falls back to Claude Haiku (same alpaca prompt) if the local model
isn't available — output format is identical either way.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config

MODEL_PATH = config.BASE_DIR / "models" / "autoredteam_lora"

ALPACA_PROMPT = """Below is an instruction that describes a task, paired with input. Write a response.

### Instruction:
{instruction}

### Input:
{input}

### Response:
"""

INSTRUCTION = (
    "You are an expert penetration tester. Analyze the following CVE and provide "
    "a structured security assessment for a pentest engagement."
)


def _load_local_model():
    """Try to load the fine-tuned LoRA model locally."""
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import PeftModel
    import torch

    BASE_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH))
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(base, str(MODEL_PATH))
    model.eval()
    return model, tokenizer


def _analyze_with_local_model(model, tokenizer, cve_text: str) -> str:
    import torch
    prompt = ALPACA_PROMPT.format(instruction=INSTRUCTION, input=cve_text)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=500,
            temperature=0.1,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return decoded.split("### Response:")[-1].strip()


def _analyze_with_claude(cve_text: str) -> str:
    """Fallback: call Claude Haiku with same alpaca prompt format."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = ALPACA_PROMPT.format(instruction=INSTRUCTION, input=cve_text)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# Module-level model cache
_model = None
_tokenizer = None
_using_local = False


def analyze_cve(cve_text: str) -> tuple[str, str]:
    """
    Analyze a CVE using the fine-tuned model (or Claude fallback).

    Returns:
        (analysis_text, model_source) where model_source is
        'fine-tuned-llama' or 'claude-haiku-fallback'
    """
    global _model, _tokenizer, _using_local

    # Try local model on first call
    if _model is None and MODEL_PATH.exists():
        try:
            from rich.console import Console
            Console().print("[cyan]Loading fine-tuned Llama model...[/]")
            _model, _tokenizer = _load_local_model()
            _using_local = True
            Console().print("[green]✓ Fine-tuned model loaded[/]")
        except Exception as e:
            Console().print(f"[yellow]Local model unavailable ({e.__class__.__name__}) — using Claude Haiku fallback[/]")
            _model = "fallback"
            _using_local = False

    if _using_local and _model != "fallback":
        return _analyze_with_local_model(_model, _tokenizer, cve_text), "fine-tuned-llama"
    else:
        return _analyze_with_claude(cve_text), "claude-haiku-fallback"
