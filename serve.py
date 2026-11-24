"""Start the Internship Watch: the web app, with its background worker.

    python serve.py
"""
import logging

import uvicorn

import config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("api:app", host=config.HOST, port=config.PORT, log_level="info")
