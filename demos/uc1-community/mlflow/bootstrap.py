"""One-shot MLflow bootstrap for the demo.

Run as the MLflow admin. It:
  1. creates the agent's service account (non-admin user),
  2. creates one experiment per Relay mode (redacted and baseline), and
  3. grants the service account EDIT on those experiments only.

It is idempotent, so it is safe to run again.
"""

from __future__ import annotations

import os
import sys
import time

import requests
from mlflow import MlflowClient
from mlflow.exceptions import RestException
from mlflow.server import get_app_client

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000").rstrip("/")
AGENT_USER = os.environ["AGENT_MLFLOW_USERNAME"]
AGENT_PASSWORD = os.environ["AGENT_MLFLOW_PASSWORD"]
EXPERIMENTS = [
    os.environ.get("REDACTED_EXPERIMENT", "uc1-customer-lookup-redacted"),
    os.environ.get("BASELINE_EXPERIMENT", "uc1-customer-lookup-baseline"),
]


def wait_for_server() -> None:
    for _ in range(90):
        try:
            if requests.get(f"{TRACKING_URI}/health", timeout=3).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    sys.exit(f"MLflow did not become healthy at {TRACKING_URI}")


def main() -> None:
    # The MLflow clients authenticate as the admin through
    # MLFLOW_TRACKING_USERNAME and MLFLOW_TRACKING_PASSWORD.
    wait_for_server()
    auth = get_app_client("basic-auth", tracking_uri=TRACKING_URI)
    tracking = MlflowClient(tracking_uri=TRACKING_URI)

    try:
        auth.get_user(AGENT_USER)
        print(f"user {AGENT_USER!r} exists")
    except Exception:
        auth.create_user(AGENT_USER, AGENT_PASSWORD)
        print(f"created user {AGENT_USER!r}")

    for name in EXPERIMENTS:
        experiment = tracking.get_experiment_by_name(name)
        experiment_id = experiment.experiment_id if experiment else tracking.create_experiment(name)
        try:
            auth.grant_user_permission(AGENT_USER, "experiment", experiment_id, "EDIT")
        except RestException as exc:
            if exc.error_code != "RESOURCE_ALREADY_EXISTS":
                raise
        print(f"experiment {name!r} (id={experiment_id}): {AGENT_USER!r} has EDIT")
    print("bootstrap complete")


if __name__ == "__main__":
    main()
