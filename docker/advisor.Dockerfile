# Advisor service (app.py): three fine-tuned Qwen3-1.7B advisors behind FastAPI.
# CPU-only image for Linux hosts / CI; on macOS run the advisor natively for MPS.
FROM python:3.12-slim

WORKDIR /srv/hima

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        torch==2.13.0 \
    && pip install --no-cache-dir \
        transformers==5.14.1 \
        accelerate==1.14.0 \
        fastapi==0.141.1 \
        uvicorn==0.52.1 \
        pydantic==2.13.4

COPY app.py .

# Weights (SNUMPR/Terran-a/b/c) download from Hugging Face on first start into
# the hf-cache volume mounted here; later starts are offline.
ENV HF_HOME=/models

EXPOSE 8090

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
