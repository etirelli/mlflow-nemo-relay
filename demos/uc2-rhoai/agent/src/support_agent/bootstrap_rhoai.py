"""Create the demo experiments in an MLflow (OpenShift AI) workspace, as a cluster user.

Run from the laptop by `make bootstrap`, with the user's own OpenShift token
(`oc whoami -t`). The agent's service account cannot create experiments: its
Role only allows `get`/`update` on these experiment names (least privilege).

    MLFLOW_TRACKING_URI=https://<gateway>/mlflow MLFLOW_TRACKING_TOKEN=... MLFLOW_WORKSPACE=<ns> \
      python -m support_agent.bootstrap_rhoai uc2-rhoai-refund-agent uc2-rhoai-refund-agent-eval ...
"""

from __future__ import annotations

import sys

from mlflow import MlflowClient


def main(names: list[str]) -> None:
    client = MlflowClient()
    for name in names:
        experiment = client.get_experiment_by_name(name)
        if experiment is not None and experiment.lifecycle_stage == "deleted":
            client.restore_experiment(experiment.experiment_id)
            print(f"restored experiment {name!r} (id={experiment.experiment_id})")
        elif experiment is not None:
            print(f"experiment {name!r} exists (id={experiment.experiment_id})")
        else:
            print(f"created experiment {name!r} (id={client.create_experiment(name)})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
