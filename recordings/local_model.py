"""The open model every recording in this book uses, pinned, fetched once and run on the CPU with llama.cpp.

Model: Qwen3-4B-Instruct-2507 (Qwen, Apache-2.0), quantized to 4-bit (Q4_K_M) GGUF. Qwen publishes no GGUF of this
model, so the file is Unsloth's conversion, pinned by repository revision and by the file's SHA-256. It is about
2.5 GB; `fetch()` downloads it once into recordings/.models/ (or the folder in RE_MODELS) and checks the hash.

Sampling follows Qwen's recommended settings for this model (temperature 0.7, top-p 0.8, top-k 20, min-p 0) with a
fixed seed, a single thread count and a cap on reply length, so a recording run repeats on the same machine. Replies
are kept raw: the book's host loop (`examples/lib/host.py`) parses them itself.
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.request
from pathlib import Path

REPOSITORY = "unsloth/Qwen3-4B-Instruct-2507-GGUF"
REVISION = "a06e946bb6b655725eafa393f4a9745d460374c9"
FILENAME = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
FILE_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
QUANTIZATION = "Q4_K_M"
SEED = 4217
THREADS = 4
CONTEXT = 4096
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "max_tokens": 256}


def fetch() -> Path:
    """The model file, downloaded at the pinned revision if it isn't here yet, and checked against its hash."""
    folder = Path(os.environ.get("RE_MODELS", Path(__file__).resolve().parent / ".models"))
    path = folder / FILENAME
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{FILENAME}"
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(url, partial)
        partial.rename(path)
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != FILE_SHA256:
        raise RuntimeError(f"{path} doesn't match its pinned SHA-256; delete it and fetch it again")
    return path


class LocalModel:
    """The pinned model behind the host loop's Model interface: complete(messages) -> raw reply text."""

    def __init__(self):
        from llama_cpp import Llama
        self.name = f"{MODEL} ({QUANTIZATION}, {REPOSITORY}@{REVISION[:7]})"
        self.llm = Llama(model_path=str(fetch()), n_ctx=CONTEXT, n_threads=THREADS, seed=SEED, verbose=False)
        self.seconds: list[float] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.llm.set_seed(SEED)                  # every call starts from the same seed, whatever ran before it
        start = time.monotonic()
        reply = self.llm.create_chat_completion(messages=messages, seed=SEED, **SAMPLING)
        self.seconds.append(round(time.monotonic() - start, 1))
        return reply["choices"][0]["message"]["content"]


def describe() -> dict:
    """What a manifest records about the model and how it ran."""
    import llama_cpp
    return {"model": MODEL, "model_version": f"{REPOSITORY}@{REVISION} {FILENAME} sha256:{FILE_SHA256}",
            "quantization": QUANTIZATION, "runner": f"llama-cpp-python {llama_cpp.__version__}, CPU, {THREADS} threads",
            "sampling": dict(SAMPLING, seed=SEED), "licence": "Apache-2.0"}
