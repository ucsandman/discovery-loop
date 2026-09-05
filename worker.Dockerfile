FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY worker-requirements.txt /tmp/worker-requirements.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/worker-requirements.txt \
    && rm /tmp/worker-requirements.txt

USER 65532:65532
WORKDIR /workspace/problem
CMD ["python", "--version"]
