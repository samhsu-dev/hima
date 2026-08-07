"""Advisor inference service: the fine-tuned suggestion trio behind HTTP.

Endpoints: /health, /infer (aggregate), /infer/{model_id}. The default app
loads its models in the application lifespan, so the server accepts requests
only once every advisor is ready.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping, Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.types import Lifespan

# The published SNUMPR checkpoints the advisor serves; fixed by the paper's
# fine-tuned Terran suggestion trio.
MODEL_TRIO = ("SNUMPR/Terran-a", "SNUMPR/Terran-b", "SNUMPR/Terran-c")


class Query(BaseModel):
    """One generation request shared by all inference endpoints."""

    prompt: str | list
    max_tokens: int = 512
    temperature: float = 0.7


class Advisor(Protocol):
    """One suggestion model behind the inference endpoints."""

    async def generate(self, query: Query) -> str: ...


class ModelAdvisor:
    """Causal-LM advisor; generation runs on the shared single worker."""

    def __init__(self, name: str, executor: ThreadPoolExecutor) -> None:
        # Imported here so importing this module stays free of the multi-
        # second transformers/torch import chain the fake-advisor path
        # never needs.
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._model = AutoModelForCausalLM.from_pretrained(
            name, device_map="auto", trust_remote_code=True)
        self._tokenizer = AutoTokenizer.from_pretrained(name)
        self._executor = executor

    async def generate(self, query: Query) -> str:
        messages = [{"role": "user", "content": query.prompt}]
        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        model_inputs = self._tokenizer([text], return_tensors="pt").to(self._model.device)
        loop = asyncio.get_running_loop()
        generated_ids = await loop.run_in_executor(
            self._executor,
            lambda: self._model.generate(
                model_inputs.input_ids,
                max_new_tokens=query.max_tokens,
                do_sample=True,
                temperature=query.temperature,
            ),
        )
        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        response = self._tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
        return response.replace("\n", "")


def create_app(advisors: Mapping[str, Advisor], lifespan: Lifespan[FastAPI] | None = None) -> FastAPI:
    """Build the advisor app over the given advisors.

    `advisors` may start empty and be filled by `lifespan`; every route
    reads it per request.
    """
    app = FastAPI(title="HIMA advisor", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "models": sorted(advisors)}

    @app.post("/infer")
    async def infer_all(query: Query) -> dict:
        model_ids = sorted(advisors)
        texts = await asyncio.gather(*(advisors[model_id].generate(query) for model_id in model_ids))
        lines = (
            f"Suggestion {chr(ord('A') + index)}: '{text}',\n"
            for index, text in enumerate(texts)
        )
        return {"text": "".join(lines)}

    @app.post("/infer/{model_id}")
    async def infer(model_id: str, query: Query) -> dict:
        if model_id not in advisors:
            raise HTTPException(status_code=404, detail="unknown model_id")
        return {"model": model_id, "text": await advisors[model_id].generate(query)}

    return app


def create_default_app() -> FastAPI:
    """Build the app whose lifespan loads the SNUMPR model trio."""
    advisors: dict[str, Advisor] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # PyTorch MPS segfaults on concurrent generate() calls; one worker
        # serializes model access.
        executor = ThreadPoolExecutor(max_workers=1)
        for index, name in enumerate(MODEL_TRIO):
            advisors[str(index)] = ModelAdvisor(name, executor)
        yield
        executor.shutdown()

    return create_app(advisors, lifespan)
