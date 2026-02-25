#!/usr/bin/env python3
import argparse, json, random

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input_json", required=True)
    ap.add_argument("--out_jsonl", required=True)
    ap.add_argument("--max_samples", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    with open(args.input_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # if wrapped
        for k in ["data","items","records","examples"]:
            if k in data and isinstance(data[k], list):
                data = data[k]
                break
    assert isinstance(data, list)

    rng.shuffle(data)
    data = data[:args.max_samples]

    def build_prompt(code: str) -> str:
        # Keep this identical between training and NLL evaluation!
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

    with open(args.out_jsonl, "w", encoding="utf-8") as out:
        for r in data:
            code = r.get("class_code", "") or ""
            comment = r.get("comment_text", "") or ""
            prompt = build_prompt(code)
            # response is the target (what SFT learns to generate)
            # Keep it as-is; do not remove anything
            out.write(json.dumps({"prompt": prompt, "response": comment}, ensure_ascii=False) + "\n")

    print(f"Wrote {len(data)} samples -> {args.out_jsonl}")

if __name__ == "__main__":
    main()
