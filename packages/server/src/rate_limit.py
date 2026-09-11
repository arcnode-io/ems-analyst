"""Shared slowapi Limiter — one instance, imported from two places.

`@limiter.limit(...)` decorators run at import time (when a controller
class is defined), before `AppModule.create_app()` exists to build one.
`app_module.py` needs the *same* instance to attach `app.state.limiter` +
the exception handler + middleware. A tiny standalone module avoids a
circular import between the two.

In-memory storage (slowapi's default) is fine here — single uvicorn
process, single container, no horizontal scaling on this deployment.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter: Limiter = Limiter(key_func=get_remote_address)
