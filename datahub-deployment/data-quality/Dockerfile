FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY run_checks.py checks.yml ./

ENTRYPOINT ["python", "-u", "run_checks.py"]
