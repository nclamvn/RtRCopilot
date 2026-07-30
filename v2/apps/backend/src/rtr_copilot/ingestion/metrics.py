from prometheus_client import Counter, Gauge, Histogram

UPLOAD_BYTES = Counter(
    "rtr_ingestion_upload_bytes_total",
    "Accepted upload bytes",
    ("detected_type",),
)
UPLOADS = Counter(
    "rtr_ingestion_upload_total",
    "Upload outcomes",
    ("result", "reason", "detected_type"),
)
QUARANTINE_DEPTH = Gauge(
    "rtr_ingestion_quarantine_depth",
    "Objects currently awaiting a terminal ingestion decision",
)
SCANNER_DURATION = Histogram(
    "rtr_ingestion_scanner_duration_seconds",
    "Malware scan duration",
    ("result",),
)
SCANNER_SIGNATURE_AGE = Gauge(
    "rtr_ingestion_scanner_signature_age_seconds",
    "Scanner signature age",
)
QUEUE_DEPTH = Gauge("rtr_ingestion_queue_depth", "Durable ingestion jobs by state", ("state",))
LEASE_EXPIRY = Counter("rtr_ingestion_lease_expiry_total", "Expired leases reclaimed")
RETRIES = Counter(
    "rtr_ingestion_retry_total",
    "Ingestion retry decisions",
    ("result",),
)
STAGE_DURATION = Histogram(
    "rtr_ingestion_stage_duration_seconds",
    "Pipeline stage latency",
    ("stage", "result"),
)
RENDITION_BYTES = Counter(
    "rtr_ingestion_rendition_bytes_total",
    "Published rendition bytes",
    ("kind",),
)
RENDITIONS = Counter(
    "rtr_ingestion_rendition_total",
    "Rendition outcomes",
    ("kind", "result"),
)
QUALITY = Histogram(
    "rtr_ingestion_quality_score",
    "Bounded OCR/transcript quality score",
    ("origin",),
    buckets=(0.25, 0.5, 0.7, 0.85, 0.95, 1.0),
)
ORPHANS = Gauge("rtr_ingestion_orphan_count", "Storage artifacts without database metadata")
