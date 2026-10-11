"""Actual canonical renderer/S3/files pipeline with synthetic scanner only.

Optional pause after actual staged renditions permits supervisor SIGKILL before
canonical publication. No policy/source/outcome service is mocked.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, '/workspace/v2/apps/backend/tests')
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_documents_integration import patch_ingestion

from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.service import DocumentOSService

async def main():
    job = uuid.UUID(os.environ['TIP054_RENDER_JOB'])
    engine = create_async_engine(os.environ['POSTGRES_DSN'].replace('postgresql://', 'postgresql+asyncpg://', 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def pause():
        Path(os.environ['TIP054_RENDER_MARKER']).write_text(json.dumps({'pid': os.getpid(), 'render_job_id': str(job), 'seam': 'actual_staged_renditions_before_canonical_publication'}))
        await asyncio.Event().wait()
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch_ingestion(patch, factory, after_render=pause if os.environ.get('TIP054_RENDER_PAUSE') == '1' else None)
            await DocumentOSService(UnitOfWork(factory)).process_render(job, worker_id='tip054-native-render')
    finally:
        await engine.dispose()

asyncio.run(main())
