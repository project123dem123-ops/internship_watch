"""The background worker: checks every source on a timer and notifies.

Each cycle fetches every source in parallel, stores what it read, reads each
new post's own page for its dates, logs the run, and sends one notification
listing everything new. A cycle can also be started from the page ("Check
now"); only one runs at a time.

Runs on a thread inside the API process (serve.py starts it), or on its own:
    python worker.py           # loop forever
    python worker.py --once    # one check, then exit
"""
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import config
import notify
import sources as src
import store

logger = logging.getLogger("internships.worker")


class Worker:
    def __init__(self, source_list=None, get=None, interval_minutes=None):
        self.sources = source_list if source_list is not None else src.SOURCES
        self.get = get                      # page fetcher; tests pass a fake one
        self.interval = (interval_minutes or config.REFRESH_MINUTES) * 60
        self._run_lock = threading.Lock()
        self._wake = threading.Event()
        self._restart_wait = False
        self._thread = None
        self.state = {"running": False, "checking": False, "started_at": None, "heartbeat": None,
                      "last_cycle": None, "next_cycle": None, "last_new": 0, "last_error": None}

    # ---- one cycle -------------------------------------------------------
    def run_cycle(self, trigger="schedule"):
        """Check every source once. Returns a summary, or None if a check was already running."""
        if not self._run_lock.acquire(blocking=False):
            return None
        self.state["checking"] = True
        run_id = store.start_run(trigger)
        ok = failed = found = 0
        fresh = []
        error = None
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda s: (s, src.check(s, self.get)), self.sources))
            for source, result in results:
                if result["error"]:
                    failed += 1
                else:
                    ok += 1
                    found += len(result["items"])
                try:
                    fresh.extend(store.record(source, result, enrich=lambda item: src.enrich(item, self.get)))
                except Exception as exc:  # noqa: BLE001 -- one source must not lose the others
                    logger.exception("Could not record %s", source["id"])
                    error = f"{source['id']}: {exc}"
            if fresh:
                delivery = notify.dispatch(fresh)
                logger.info("%d new internship(s); notified on %s", len(fresh),
                            ", ".join(d["channel"] for d in delivery["deliveries"] if d["ok"]))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Check failed")
            error = f"{type(exc).__name__}: {exc}"
        finally:
            store.finish_run(run_id, ok, failed, found, len(fresh), error)
            self.state.update(checking=False, last_cycle=store.now(), last_new=len(fresh), last_error=error)
            self._run_lock.release()
        return {"run_id": run_id, "sources_ok": ok, "sources_failed": failed, "found": found,
                "new": fresh, "error": error}

    # ---- the timer --------------------------------------------------------
    def _loop(self, first_delay):
        if first_delay:
            self._wake.wait(first_delay)
            self._wake.clear()
        while self.state["running"]:
            self.state["heartbeat"] = store.now()
            try:
                self.run_cycle("schedule")
            except Exception:  # noqa: BLE001 -- the worker must outlive one bad cycle
                logger.exception("Cycle crashed")
            self.state["next_cycle"] = (datetime.now(timezone.utc) + timedelta(seconds=self.interval)).isoformat(timespec="seconds")
            # Sleep in short steps so the heartbeat shows the worker is alive.
            deadline = time.time() + self.interval
            while self.state["running"] and time.time() < deadline:
                self.state["heartbeat"] = store.now()
                if self._wake.wait(min(30, max(1, deadline - time.time()))):
                    self._wake.clear()
                    if self._restart_wait:          # a new interval: wait that long from now
                        self._restart_wait = False
                        deadline = time.time() + self.interval
                        continue
                    break

    def start(self, first_delay=None):
        if self._thread and self._thread.is_alive():
            return
        self.state.update(running=True, started_at=store.now())
        self._thread = threading.Thread(target=self._loop, name="internship-worker", daemon=True,
                                        args=(config.FIRST_CHECK_DELAY if first_delay is None else first_delay,))
        self._thread.start()
        logger.info("Worker started: %d sources every %d min", len(self.sources), self.interval // 60)

    def stop(self):
        self.state["running"] = False
        self._wake.set()

    def set_interval(self, minutes):
        """A new timer, applied from the next wait (the current one is cut short)."""
        self.interval = max(5, int(minutes)) * 60
        if self.state["next_cycle"] and not self.state["checking"]:
            self.state["next_cycle"] = (datetime.now(timezone.utc) + timedelta(seconds=self.interval)).isoformat(timespec="seconds")
            self._restart_wait = True
            self._wake.set()

    def check_now(self):
        """Run a check now, off the caller's thread. False if one is running."""
        if self.state["checking"]:
            return False
        threading.Thread(target=self.run_cycle, args=("manual",), name="internship-check-now", daemon=True).start()
        return True

    def alive(self):
        return bool(self._thread and self._thread.is_alive())


worker = Worker()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "--once" in sys.argv:
        summary = worker.run_cycle("manual")
        print(f"sources ok {summary['sources_ok']}, failed {summary['sources_failed']}, "
              f"found {summary['found']}, new {len(summary['new'])}")
        for item in summary["new"]:
            print(f"  NEW [{item['level']}] {item['title']} -> {item.get('url')}")
    else:
        worker.start(first_delay=0)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            worker.stop()
