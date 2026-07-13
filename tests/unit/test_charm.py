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
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import ops
from ops import testing

from charm import FastAPIDemoCharm

# The OCI image (built from a rock) ships with a built-in Pebble layer that
# defines the ``fastapi`` service with a default command, startup, environment,
# and health check. The charm uses ``override: merge`` so it only needs to
# override the command (for the configured port) and the environment (for
# database credentials). To test this in isolation, we reproduce the rock's
# base layer here.
# See https://github.com/canonical/api_demo_server/blob/master/rockcraft.yaml
ROCK_BASE_LAYER = ops.pebble.Layer(
    {
        "summary": "FastAPI demo server",
        "description": "Base layer from the OCI image",
        "services": {
            "fastapi": {
                "override": "replace",
                "summary": "FastAPI demo server",
                "command": "/bin/uvicorn api_demo_server.app:app --host 0.0.0.0 --port 8000",
                "startup": "enabled",
                "environment": {"DEMO_SERVER_LOGFILE": "/tmp/demo_server.log"},
                "on-check-failure": {"server-up": "restart"},
            }
        },
        "checks": {
            "server-up": {
                "override": "replace",
                "period": "1s",
                "timeout": "5s",
                "threshold": 5,
                "http": {"url": "http://127.0.0.1:8000/version"},
            }
        },
    }
)


def test_pebble_layer():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(
        name="demo-server",
        can_connect=True,
        layers={"rock": ROCK_BASE_LAYER},
    )
    state_in = testing.State(
        containers={container},
        leader=True,
    )
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
    # Expected plan after Pebble ready with default config.
    # The charm uses ``override: merge`` so only the command and environment
    # are overridden; the rest (summary, startup, on-check-failure, checks)
    # is inherited from the rock's base layer.
    expected_plan = {
        "services": {
            "fastapi": {
                "override": "merge",
                "summary": "FastAPI demo server",
                "command": "uvicorn api_demo_server.app:app --host=0.0.0.0 --port=8000",
                "startup": "enabled",
                "environment": {"DEMO_SERVER_LOGFILE": "/tmp/demo_server.log"},
                "on-check-failure": {"server-up": "restart"},
            }
        },
        "checks": {
            "server-up": {
                "override": "replace",
                "period": "1s",
                "timeout": "5s",
                "threshold": 5,
                "http": {"url": "http://127.0.0.1:8000/version"},
            }
        },
    }

    # Check that we have the plan we expected:
    assert state_out.get_container(container.name).plan == expected_plan
    # Check the unit is blocked:
    assert state_out.unit_status == testing.BlockedStatus("Waiting for database relation")
    # Check the service was started:
    assert (
        state_out.get_container(container.name).service_statuses["fastapi"]
        == ops.pebble.ServiceStatus.ACTIVE
    )


def test_config_changed():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        config={"server-port": 8080},
        leader=True,
    )
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    command = (
        state_out.get_container(container.name).layers["fastapi_demo"].services["fastapi"].command
    )
    assert "--port=8080" in command


def test_config_changed_invalid_port():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        config={"server-port": 22},
        leader=True,
    )
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.BlockedStatus(
        "Invalid port number, 22 is reserved for SSH"
    )


def test_relation_data():
    ctx = testing.Context(FastAPIDemoCharm)
    relation = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql-k8s",
        remote_app_data={
            "endpoints": "example.com:5432",
            "username": "foo",
            "password": "bar",
        },
    )
    container = testing.Container(
        name="demo-server",
        can_connect=True,
        layers={"rock": ROCK_BASE_LAYER},
    )
    state_in = testing.State(
        containers={container},
        relations={relation},
        leader=True,
    )

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    # Check the combined plan's environment, which includes both the rock's
    # DEMO_SERVER_LOGFILE (inherited via override: merge) and the charm's
    # database credentials.
    assert state_out.get_container(container.name).plan.services["fastapi"].environment == {
        "DEMO_SERVER_LOGFILE": "/tmp/demo_server.log",
        "DEMO_SERVER_DB_HOST": "example.com",
        "DEMO_SERVER_DB_PORT": "5432",
        "DEMO_SERVER_DB_USER": "foo",
        "DEMO_SERVER_DB_PASSWORD": "bar",
    }


def test_no_database_blocked():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        leader=True,
    )  # We've omitted relation data from the input state.

    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    assert state_out.unit_status == testing.BlockedStatus("Waiting for database relation")


def test_get_db_info_action():
    ctx = testing.Context(FastAPIDemoCharm)
    relation = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql-k8s",
        remote_app_data={
            "endpoints": "example.com:5432",
            "username": "foo",
            "password": "bar",
        },
    )
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        relations={relation},
        leader=True,
    )

    ctx.run(ctx.on.action("get-db-info", params={"show-password": False}), state_in)

    assert ctx.action_results == {
        "db-host": "example.com",
        "db-port": "5432",
    }


def test_get_db_info_action_show_password():
    ctx = testing.Context(FastAPIDemoCharm)
    relation = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql-k8s",
        remote_app_data={
            "endpoints": "example.com:5432",
            "username": "foo",
            "password": "bar",
        },
    )
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        relations={relation},
        leader=True,
    )

    ctx.run(ctx.on.action("get-db-info", params={"show-password": True}), state_in)

    assert ctx.action_results == {
        "db-host": "example.com",
        "db-port": "5432",
        "db-username": "foo",
        "db-password": "bar",
    }
