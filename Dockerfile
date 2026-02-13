FROM python:3.9-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory structure for cache and saved files (if they don't exist in copy)
RUN mkdir -p imd_cache savedTAFs

# Expose port (Flask default 5000)
EXPOSE 5000

# Command to run the application using Gunicorn (Production)
# 4 workers, binding to 0.0.0.0:5000
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000", "app:app"]
