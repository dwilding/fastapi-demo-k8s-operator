# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import contextlib
import logging
import pathlib
import time

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@contextlib.contextmanager
def _timed_step(label: str):
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        logger.info("[timing] %s: %.2fs", label, elapsed)


def test_full_integration_flow(charm: pathlib.Path, juju: jubilant.Juju):
    """Run the full deploy/remove/integrate flow in a single module-scoped model."""
    resources = {
        "demo-server-image": METADATA["resources"]["demo-server-image"]["upstream-source"]
    }

    with _timed_step("test_deploy_app"):
        juju.deploy(charm.resolve(), app=APP_NAME, resources=resources)
        juju.wait(jubilant.all_blocked, timeout=10 * 60)

    for i in range(1, 11):
        with _timed_step(f"test_deploy_postgres iter={i}"):
            juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
            juju.wait(
                lambda status: jubilant.all_active(status, "postgresql-k8s"), timeout=10 * 60
            )

        if i < 10:
            with _timed_step(f"test_remove_postgres iter={i}"):
                juju.remove_application("postgresql-k8s")
                juju.wait(lambda status: jubilant.all_blocked(status, APP_NAME), timeout=10 * 60)

    with _timed_step("test_integrate"):
        juju.integrate(APP_NAME, "postgresql-k8s")
        juju.wait(jubilant.all_active, timeout=10 * 60)
