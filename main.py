import math
import time
import uuid
from collections import deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

EMAIL = "23f2001563@ds.study.iitm.ac.in"
ASSIGNED_ORIGIN = "https://app-7yp3qe.example.com"
EXAM_ORIGIN = "https://exam.sanand.workers.dev"   # the exam page that runs the browser checks
EXAM_ORIGIN_REGEX = r"https://([a-z0-9-]+\.)*sanand\.workers\.dev"

RATE_LIMIT = 13      # requests per client per window
WINDOW = 10.0        # seconds

app = FastAPI()

_hits: dict = {}     # client id -> deque of request timestamps (sliding window)


def _now() -> float:
    return time.monotonic()


# Middleware order: add_middleware() makes the LAST one added the OUTERMOST.
# Request flow:  CORS -> request context -> rate limit -> route
# So CORS headers and X-Request-ID are present even on 429 responses.

# ---------- Middleware 3: per-client rate limit (innermost) ----------
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    client = (request.headers.get("x-client-id") or "").strip()
    if request.method == "OPTIONS" or not client:
        return await call_next(request)

    now = _now()
    if len(_hits) > 10000:  # housekeeping
        for cid in [c for c, d in _hits.items() if not d or now - d[-1] >= WINDOW]:
            del _hits[cid]

    window = _hits.setdefault(client, deque())
    while window and now - window[0] >= WINDOW:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        retry_after = max(1, math.ceil(window[0] + WINDOW - now))
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded", "request_id": request.state.request_id},
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)
    return await call_next(request)


# ---------- Middleware 1: request context ----------
@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = (request.headers.get("x-request-id") or "").strip() or str(uuid.uuid4())
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# ---------- Middleware 2: CORS (outermost) ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ASSIGNED_ORIGIN, EXAM_ORIGIN],
    allow_origin_regex=EXAM_ORIGIN_REGEX,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-Request-ID", "X-Client-Id", "Content-Type"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


@app.get("/ping")
def ping(request: Request):
    return {"email": EMAIL, "request_id": request.state.request_id}


@app.get("/")
def root():
    return {"status": "ok"}