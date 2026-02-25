#!/usr/bin/env python3
import argparse, json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

def build_prompt(code: str) -> str:
    return (
        "You are a helpful assistant for Java developers.\n"
        "Task: Write a concise JavaDoc-style class comment for the given Java class.\n"
        "Return only the comment text.\n\n"
        "Java class:\n"
        "```java\n"
        f"{code}\n"
        "```\n\n"
        "Comment:\n"
    )

@torch.no_grad()
def mean_nll_of_target(model, tok, prompt: str, target: str, device: str):
    prompt_ids = tok(prompt, return_tensors="pt").input_ids.to(device)
    full = tok(prompt + target, return_tensors="pt").input_ids.to(device)

    labels = full.clone()
    labels[:, :prompt_ids.shape[1]] = -100

    out = model(full, labels=labels)
    num_toks = int((labels != -100).sum().item())
    loss_mean = float(out.loss.item())  # mean over target tokens
    return loss_mean, num_toks

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_dir", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out_json", required=True)
    args = ap.parse_args()

    meta = json.load(open(args.meta, "r", encoding="utf-8"))
    host_code = meta.get("host_class_code", "")
    if not host_code:
        raise ValueError("meta.json missing 'host_class_code'. Patch build_cap_sft_jsonl.py to include it.")

    tok = AutoTokenizer.from_pretrained(args.model_dir, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model_dir,
        device_map="auto",
        torch_dtype=torch.float16,
    )
    model.eval()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    prompt = build_prompt(host_code)
    target = meta["inserted_text"]

    loss_mean, ntok = mean_nll_of_target(model, tok, prompt, target, device)

    out = dict(meta)
    out["tokens"] = ntok
    out["mean_nll_per_token"] = loss_mean

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {args.out_json}")

if __name__ == "__main__":
    main()
