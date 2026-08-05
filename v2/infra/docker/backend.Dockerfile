FROM python:3.12.4-slim@sha256:a3e58f9399353be051735f09be0316bfdeab571a5c6a24fd78b92df85bcb2d85 AS builder
WORKDIR /app
RUN pip install --no-cache-dir uv==0.8.11
COPY apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY apps/backend/src ./src
COPY apps/backend/alembic.ini ./alembic.ini
COPY apps/backend/migrations ./migrations
RUN uv sync --frozen --no-dev

FROM python:3.12.4-slim@sha256:a3e58f9399353be051735f09be0316bfdeab571a5c6a24fd78b92df85bcb2d85 AS speech-model
ARG VOSK_MODEL_URL=https://github.com/BartekReterski/VoskModels/releases/download/v1/vosk-model-small-en-us-0.15.zip
ARG VOSK_MODEL_SHA256=30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498
RUN MODEL_URL="$VOSK_MODEL_URL" MODEL_SHA256="$VOSK_MODEL_SHA256" python - <<'PY'
import hashlib
import os
import pathlib
import urllib.request
import zipfile

archive = pathlib.Path("/tmp/vosk-model.zip")
with urllib.request.urlopen(os.environ["MODEL_URL"], timeout=120) as response:
    archive.write_bytes(response.read())
actual = hashlib.sha256(archive.read_bytes()).hexdigest()
if actual != os.environ["MODEL_SHA256"]:
    raise SystemExit("vosk_model_checksum_mismatch")
with zipfile.ZipFile(archive) as package:
    if any(
        name.startswith(("/", "\\")) or ".." in pathlib.PurePosixPath(name).parts
        for name in package.namelist()
    ):
        raise SystemExit("vosk_model_archive_unsafe")
    package.extractall("/model")
(pathlib.Path("/model/vosk-model-small-en-us-0.15") / ".archive-sha256").write_text(
    actual + "\n",
)
PY

FROM python:3.12.4-slim@sha256:a3e58f9399353be051735f09be0316bfdeab571a5c6a24fd78b92df85bcb2d85
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
LABEL org.rtr.vosk.model="vosk-model-small-en-us-0.15" \
  org.rtr.vosk.model.license="Apache-2.0" \
  org.rtr.vosk.model.sha256="30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"
WORKDIR /app
RUN mkdir -p /usr/local/share/fonts/truetype/be-vietnam-pro
ADD --checksum=sha256:cd1ef6e9d7db28ad5cdb88a65ccbe693870e60d340b791f349d248342b4fe4c3 \
  https://raw.githubusercontent.com/google/fonts/2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/bevietnampro/BeVietnamPro-Regular.ttf \
  /usr/local/share/fonts/truetype/be-vietnam-pro/BeVietnamPro-Regular.ttf
ADD --checksum=sha256:7f738fe5c43c8872807b20e2d30d42163618de8a4daf7f48a939adac32c16847 \
  https://raw.githubusercontent.com/google/fonts/2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/bevietnampro/BeVietnamPro-Bold.ttf \
  /usr/local/share/fonts/truetype/be-vietnam-pro/BeVietnamPro-Bold.ttf
ADD --checksum=sha256:a33ebb3f68e0e260a7d3874d64259ad309971a2daf969e7ce5f444d70bce535f \
  https://raw.githubusercontent.com/google/fonts/2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/bevietnampro/BeVietnamPro-Italic.ttf \
  /usr/local/share/fonts/truetype/be-vietnam-pro/BeVietnamPro-Italic.ttf
ADD --checksum=sha256:a2a65bdf9b251beb3d658ae691889d71ce63c0290940c87ca60b449ceb0bdaee \
  https://raw.githubusercontent.com/google/fonts/2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/bevietnampro/BeVietnamPro-BoldItalic.ttf \
  /usr/local/share/fonts/truetype/be-vietnam-pro/BeVietnamPro-BoldItalic.ttf
RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
      espeak-ng=1.51+dfsg-10+deb12u2 \
      ffmpeg=7:5.1.9-0+deb12u1 \
      fonts-dejavu-core=2.37-6 \
      fonts-liberation=1:1.07.4-11 \
      fonts-noto-core=20201225-1 \
      libatomic1=12.2.0-14+deb12u1 \
      libreoffice-impress=4:7.4.7-1+deb12u14 \
      libreoffice-writer=4:7.4.7-1+deb12u14 \
      libseccomp2=2.5.4-1+deb12u1 \
      tesseract-ocr=5.3.0-2 \
      tesseract-ocr-eng=1:4.1.0-2 \
      tesseract-ocr-osd=1:4.1.0-2 \
    && apt-get upgrade --yes \
    && fc-cache -f \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY --from=builder --chown=app:app /app /app
COPY --from=speech-model --chown=app:app \
  /model/vosk-model-small-en-us-0.15 \
  /opt/rtr/models/vosk-model-small-en-us-0.15
USER app
CMD ["uvicorn", "rtr_copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
