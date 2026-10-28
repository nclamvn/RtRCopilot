"""Thin provider-boundary guard, inside DBOS model steps, not another executor."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
import asyncio

from dbos import DBOS
from pydantic_ai.models.wrapper import WrapperModel

from .store import WorkspaceError

run_scope = ContextVar("workspace_run_scope", default=None)


class DispatchGuard(WrapperModel):
    def __init__(self, wrapped, store, *, simulation=False):
        super().__init__(wrapped)
        self.store, self.simulation = store, simulation
        self.io_slots = asyncio.Semaphore(2)

    def reserve(self, run_context=None):
        scope = run_context.deps if run_context is not None else run_scope.get()
        step_id = DBOS.step_id
        if scope is None or step_id is None:
            raise WorkspaceError("provider_dispatch_outside_durable_scope")
        self.store.reserve_model_dispatch(scope.owner, scope.run_id, step_id,
                                          allow_replay=self.simulation)

    async def request(self, messages, model_settings, model_request_parameters):
        try:
            async with self.io_slots:
                self.reserve()
                return await self.wrapped.request(messages, model_settings, model_request_parameters)
        except WorkspaceError:
            raise
        except Exception:
            # Never checkpoint raw provider exceptions/request objects containing headers.
            raise WorkspaceError("provider_request_failed") from None

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        try:
            async with self.io_slots:
                self.reserve(run_context)
                async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as stream:
                    yield stream
        except WorkspaceError:
            raise
        except Exception:
            raise WorkspaceError("provider_request_failed") from None
