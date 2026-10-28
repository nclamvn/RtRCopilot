"""Thin provider-boundary guard, inside DBOS model steps, not another executor."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
import asyncio

from dbos import DBOS
from pydantic_ai.models.wrapper import WrapperModel

from .store import WorkspaceError

run_scope = ContextVar("workspace_run_scope", default=None)


class DispatchGuard(WrapperModel):
    def __init__(self, wrapped, store, *, simulation=False, budget=None):
        super().__init__(wrapped)
        self.store, self.simulation = store, simulation
        self.budget = budget
        self.io_slots = asyncio.Semaphore(2)

    def reserve(self, run_context=None):
        scope = run_context.deps if run_context is not None else run_scope.get()
        step_id = DBOS.step_id
        if scope is None or step_id is None:
            raise WorkspaceError("provider_dispatch_outside_durable_scope")
        self.store.reserve_model_dispatch(scope.owner, scope.run_id, step_id,
                                          allow_replay=self.simulation)

    async def request(self, messages, model_settings, model_request_parameters):
        ticket = None
        try:
            async with self.io_slots:
                self.reserve()
                if self.budget:
                    ticket = await self.budget.reserve(run_scope.get(), messages, model_settings, model_request_parameters)
                response = await self.wrapped.request(messages, model_settings, model_request_parameters)
                if ticket:
                    await self.budget.settle(ticket, response.usage.input_tokens, response.usage.output_tokens)
                return response
        except BaseException as exc:
            if ticket:
                await self.budget.unknown(ticket)
            if isinstance(exc, (WorkspaceError, asyncio.CancelledError)):
                raise
            raise WorkspaceError("provider_request_failed") from None

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        ticket = None
        try:
            async with self.io_slots:
                self.reserve(run_context)
                if self.budget:
                    scope = run_context.deps if run_context else run_scope.get()
                    ticket = await self.budget.reserve(scope, messages, model_settings, model_request_parameters)
                async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as stream:
                    yield stream
                    if ticket:
                        usage = stream.usage
                        await self.budget.settle(ticket, usage.input_tokens, usage.output_tokens)
        except BaseException as exc:
            if ticket:
                await self.budget.unknown(ticket)
            if isinstance(exc, (WorkspaceError, asyncio.CancelledError)):
                raise
            raise WorkspaceError("provider_request_failed") from None
