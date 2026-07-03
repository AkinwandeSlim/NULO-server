"""
Rate limiting middleware for NuloAfrica server
Uses slowapi with limits library
Install requirements:
    pip install slowapi limits
"""

from fastapi import Request, HTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Initialize limiter with remote address as key
limiter = Limiter(key_func=get_remote_address)

def setup_rate_limiter(app):
    """Setup rate limiting for the FastAPI app"""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Decorators for common rate limits
from slowapi import Limiter
from slowapi.util import get_remote_address

# Example usage:
# @limiter.limit("5/minute")
# async def some_endpoint():
#     ...
