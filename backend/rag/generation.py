from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
import torch

model_name = "moussaKam/barthez"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
device = 0 if torch.cuda.is_available() else -1
generator = pipeline("text2text-generation", model=model, tokenizer=tokenizer, device=device)

def generate(text):
    outputs = generator(text, max_new_tokens=100, do_sample=True, temperature=0.75)
    return outputs[0]["generated_text"].strip()
