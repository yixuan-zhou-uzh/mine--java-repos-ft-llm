#!/usr/bin/env python3
import argparse, json, time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

def log(msg: str):
    print(msg, flush=True)

def build_prompt(code: str) -> str:
    return (
        "You are a helpful assistant for Java developers.\n"
        "Task: Write a concise class comment for the given Java class.\n"
        "Return only the comment text.\n\n"
        "Java class:\n"
        "```java\n"
        f"{code}\n"
        "```\n\n"
        "Comment:\n"
    )

@torch.no_grad()
def mean_nll_of_target(model, tok, prompt: str, target: str, device: str):
    t0 = time.time()
    prompt_ids = tok(prompt, return_tensors="pt").input_ids.to(device)
    t1 = time.time()
    full = tok(prompt + target, return_tensors="pt").input_ids.to(device)
    t2 = time.time()

    labels = full.clone()
    labels[:, :prompt_ids.shape[1]] = -100

    # Forward pass (this is usually the slowest part on CPU)
    out = model(full, labels=labels)
    t3 = time.time()

    num_toks = int((labels != -100).sum().item())
    loss_mean = float(out.loss.item())  # mean over target tokens

    stats = {
        "prompt_tokens": int(prompt_ids.shape[1]),
        "full_tokens": int(full.shape[1]),
        "target_tokens": num_toks,
        "time_tokenize_prompt_s": t1 - t0,
        "time_tokenize_full_s": t2 - t1,
        "time_forward_s": t3 - t2,
        "time_total_compute_s": t3 - t0,
    }
    return loss_mean, num_toks, stats

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_dir", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out_json", required=True)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--dtype", choices=["auto", "float16", "bfloat16", "float32"], default="auto")
    args = ap.parse_args()

    t_start = time.time()
    log("[1/7] Loading meta.json ...")
    with open(args.meta, "r", encoding="utf-8") as f:
        meta = json.load(f)
    host_code = meta.get("host_class_code", "")
    if not host_code:
        raise ValueError("meta.json missing 'host_class_code'. Patch build_cap_sft_jsonl.py to include it.")
    target = meta["inserted_text"]

    if args.verbose:
        log(f"  - family={meta.get('family')} insert_type={meta.get('insert_type')} k={meta.get('k')}")
        log(f"  - canary_id={meta.get('canary_id')}")
        log(f"  - inserted_text preview: {target[:120].replace(chr(10),' ')}{'...' if len(target)>120 else ''}")

    # Device selection
    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("You set --device cuda but torch.cuda.is_available() is False.")

    # Dtype selection (important: float16 on CPU is usually bad)
    if args.dtype == "auto":
        dtype = torch.float16 if device == "cuda" else torch.float32
    elif args.dtype == "float16":
        dtype = torch.float16
    elif args.dtype == "bfloat16":
        dtype = torch.bfloat16
    else:
        dtype = torch.float32

    log(f"[2/7] Loading tokenizer from {args.model_dir} ...")
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(args.model_dir, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    log(f"      done in {time.time()-t0:.2f}s")

    log(f"[3/7] Loading model from {args.model_dir} (device={device}, dtype={dtype}) ...")
    t0 = time.time()

    # On CPU we avoid device_map="auto" because it adds overhead and can be confusing.
    if device == "cpu":
        model = AutoModelForCausalLM.from_pretrained(args.model_dir, torch_dtype=dtype)
        model.to("cpu")
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_dir,
            device_map="auto",
            torch_dtype=dtype,
        )

    model.eval()
    log(f"      done in {time.time()-t0:.2f}s")

    log("[4/7] Building prompt ...")
    prompt = build_prompt(host_code)
    log(f"      prompt_chars={len(prompt)} target_chars={len(target)}")

    log("[5/7] Computing teacher-forcing NLL (tokenize + forward pass) ...")
    loss_mean, ntok, stats = mean_nll_of_target(model, tok, prompt, target, device=device)
    log(f"      forward done. mean_nll_per_token={loss_mean:.6f} target_tokens={ntok}")
    log(f"      tokenize_prompt={stats['time_tokenize_prompt_s']:.2f}s "
        f"tokenize_full={stats['time_tokenize_full_s']:.2f}s forward={stats['time_forward_s']:.2f}s "
        f"total_compute={stats['time_total_compute_s']:.2f}s")
    log(f"      prompt_tokens={stats['prompt_tokens']} full_tokens={stats['full_tokens']}")

    log("[6/7] Writing result JSON ...")
    out = dict(meta)
    out["tokens"] = ntok
    out["mean_nll_per_token"] = loss_mean
    out["debug"] = {
        "device": device,
        "dtype": str(dtype),
        **stats,
    }

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    log("[7/7] Done.")
    log(f"Wrote {args.out_json}")
    log(f"Total elapsed: {time.time()-t_start:.2f}s")

if __name__ == "__main__":
    main()