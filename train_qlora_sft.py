#!/usr/bin/env python3
import argparse
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
from trl import SFTTrainer
from peft import LoraConfig
import os

def has_cuda():
    return torch.cuda.is_available()

def can_use_bnb_4bit():
    if not has_cuda():
        return False
    try:
        import bitsandbytes as bnb  # noqa
        return True
    except Exception:
        return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="codellama/CodeLlama-7b-Instruct-hf")
    ap.add_argument("--train_jsonl", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--max_steps", type=int, default=400)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch_size", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--seq_len", type=int, default=2048)
    ap.add_argument("--smoke_test", action="store_true",
                help="If set, run a cheap CPU-friendly test model when 4-bit CUDA is unavailable.")
    ap.add_argument("--smoke_model", default="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                help="Small model for smoke tests on machines without CUDA/bnb.")
    args = ap.parse_args()

    model_name = args.model
    use_4bit = can_use_bnb_4bit()

    if args.smoke_test and not use_4bit:
        print("[SMOKE TEST] CUDA/bnb 4-bit unavailable. Switching to small CPU model:", args.smoke_model)
        model_name = args.smoke_model

    ds = load_dataset("json", data_files=args.train_jsonl, split="train")

    tok = AutoTokenizer.from_pretrained(model_name, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    do_peft = not args.smoke_test  # keep smoke test simplest

    if use_4bit and model_name == args.model:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=bnb_config,
            device_map="auto",
        )
    else:
        # CPU or normal GPU without bnb 4bit
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
        )

    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )

    def formatting(ex):
        # prompt+response is the supervised target
        return ex["prompt"] + ex["response"]


    # Use bitsandbytes optimizer only when we are actually doing 4-bit on CUDA.
    use_bnb_optim = use_4bit and (model_name == args.model)
    optim_name = "paged_adamw_8bit" if use_bnb_optim else "adamw_torch"
    
    training_args = TrainingArguments(
        output_dir=args.out_dir,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=20,
        save_steps=100,
        save_total_limit=2,
        fp16=has_cuda(),
        optim=optim_name,
        report_to="none",
    )

    # ---- TRL SFTTrainer API compatibility (tokenizer vs processing_class) ----
    trainer_kwargs = dict(
        model=model,
        train_dataset=ds,
        max_seq_length=args.seq_len,
        formatting_func=formatting,
        args=training_args,
    )
    if do_peft:
        trainer_kwargs["peft_config"] = lora

    # Newer TRL uses `processing_class`, older uses `tokenizer`,
    # and some versions accept neither but infer from model.
    try:
        trainer = SFTTrainer(**trainer_kwargs, tokenizer=tok)
    except TypeError:
        try:
            trainer = SFTTrainer(**trainer_kwargs, processing_class=tok)
        except TypeError:
            trainer = SFTTrainer(**trainer_kwargs)

    trainer.train()
    trainer.save_model(args.out_dir)
    tok.save_pretrained(args.out_dir)

    print(f"Saved adapter/model artifacts to {args.out_dir}")

if __name__ == "__main__":
    main()