"""The Internship Watch web app: the page, and the JSON it reads."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

import config
import notify
import sources as src
import store
from worker import worker

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@asynccontextmanager
async def lifespan(_app):
    # The background worker lives as long as the web app. A check interval
    # saved on the page outlasts restarts.
    saved = store.get_setting("refresh_minutes")
    if saved:
        worker.set_interval(int(saved))
    if config.WORKER:
        worker.start()
    yield
    worker.stop()


app = FastAPI(title="Internship Watch", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True, "worker": worker.alive() or not config.WORKER}


@app.get("/", include_in_schema=False)
def page():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/static/{name}", include_in_schema=False)
def static(name: str):
    path = os.path.join(STATIC, os.path.basename(name))
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.get("/api/items")
def items():
    """Internships and jobs still open to apply for; `closed` counts the ones hidden."""
    return {"items": [dict(i, source=src.SOURCE_BY_ID.get(i["source_id"], {}).get("name", i["source_id"]))
                      for i in store.items()],
            "closed": store.closed_count(), "today": src.today().isoformat()}


@app.get("/api/status")
def status():
    states = store.source_states()
    listed = []
    for s in src.SOURCES:
        st = states.get(s["id"], {})
        listed.append({"id": s["id"], "name": s["name"], "level": s["level"], "kind": s["kind"], "home": s["home"],
                       "jobs": bool(s.get("jobs")),
                       "last_check": st.get("last_check"), "last_ok": st.get("last_ok"),
                       "status": st.get("status") or "not checked yet", "found": st.get("found") or 0,
                       "pages": st.get("pages") or []})
    return {"worker": dict(worker.state, alive=worker.alive(), enabled=config.WORKER,
                           interval_minutes=worker.interval // 60),
            "sources": listed, "runs": store.runs(15), "channels": notify.active_channels()}


@app.post("/api/check")
def check_now():
    started = worker.check_now()
    return JSONResponse({"started": started, "checking": True}, status_code=202 if started else 200)


@app.get("/api/settings")
def get_settings():
    return {"refresh_minutes": worker.interval // 60}


@app.post("/api/settings")
async def save_settings(request: Request):
    body = await _json(request)
    try:
        minutes = int(body.get("refresh_minutes"))
    except (TypeError, ValueError):
        raise HTTPException(400, "refresh_minutes must be a whole number of minutes.")
    if not 5 <= minutes <= 1440:
        raise HTTPException(400, "Choose between 5 and 1440 minutes.")
    store.set_setting("refresh_minutes", minutes)
    worker.set_interval(minutes)
    return {"refresh_minutes": minutes}


@app.get("/api/notifications")
def notifications():
    rows, unread = store.notifications(50)
    return {"notifications": rows, "unread": unread}


@app.post("/api/notifications/read")
async def read(request: Request):
    body = await _json(request)
    store.mark_read([int(i) for i in body.get("ids", []) if str(i).isdigit()] or None)
    return {"ok": True}


@app.get("/api/channels")
def channels():
    return notify.public_config()


@app.post("/api/channels/{name}")
async def save_channel(name: str, request: Request):
    if name not in notify.FIELDS:
        raise HTTPException(404, "Unknown channel.")
    return notify.save_config(name, await _json(request))


@app.post("/api/channels/{name}/test")
def test_channel(name: str):
    if name not in notify.FIELDS and name != "all":
        raise HTTPException(404, "Unknown channel.")
    return notify.send_test(None if name == "all" else name)


async def _json(request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}
