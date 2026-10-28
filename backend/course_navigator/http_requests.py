"""Per-request HTTP ownership with cancellation of asynchronous socket waits."""
import asyncio
from collections.abc import Callable

import httpx


class RequestCancelled(Exception):
    pass


def post_cancellable(url: str, *, should_cancel: Callable[[], bool], timeout, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        if should_cancel():
            raise RequestCancelled()
        async with httpx.AsyncClient(timeout=timeout) as client:
            request = asyncio.create_task(client.post(url, **kwargs))
            try:
                while not request.done():
                    await asyncio.wait({request}, timeout=0.1)
                    if should_cancel():
                        raise RequestCancelled()
                if should_cancel():
                    raise RequestCancelled()
                return await request
            finally:
                if not request.done():
                    request.cancel()
                await asyncio.gather(request, return_exceptions=True)

    # Callers are synchronous backend workers; each owns its event loop/client.
    return asyncio.run(send())
