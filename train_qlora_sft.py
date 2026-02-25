#!/usr/bin/env python3
import argparse
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
from trl import SFTTrainer
from peft import LoraConfig

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
    args = ap.parse_args()

    ds = load_dataset("json", data_files=args.train_jsonl, split="train")

    tok = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    # ✅ Correct way to enable 4-bit QLoRA in modern transformers
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb_config,
        device_map="auto",
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

    training_args = TrainingArguments(
        output_dir=args.out_dir,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=20,
        save_steps=100,
        save_total_limit=2,
        fp16=True,
        optim="paged_adamw_8bit",
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tok,
        train_dataset=ds,
        peft_config=lora,
        max_seq_length=args.seq_len,
        formatting_func=formatting,
        args=training_args,
    )

    trainer.train()
    trainer.save_model(args.out_dir)
    tok.save_pretrained(args.out_dir)

    print(f"Saved adapter/model artifacts to {args.out_dir}")

if __name__ == "__main__":
    main()