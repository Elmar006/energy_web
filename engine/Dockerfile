FROM python:3.13.7-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY energy ./energy
USER 65532:65532
EXPOSE 8090
CMD ["uvicorn", "energy.api:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
