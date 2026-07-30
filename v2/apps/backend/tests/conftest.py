import os

os.environ.setdefault("POSTGRES_DSN", "postgresql://user:password@localhost:5432/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY", "local")
os.environ.setdefault("S3_SECRET_KEY", "local-secret")
os.environ.setdefault("S3_BUCKET", "rtr-test")
