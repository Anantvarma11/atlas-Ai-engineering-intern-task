FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full project (includes canonical.db if already built)
COPY . .
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
