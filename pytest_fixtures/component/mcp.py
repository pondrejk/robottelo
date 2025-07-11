import pytest

from robottelo.config import settings


@pytest.fixture(scope='module')
def module_mcp_target_sat(module_target_sat):
    """A module-level fixture to provide an MCP server configured on Satellite"""
    # TODO
    # 1. register to the registry to get the container image from
    # 2. open port for the container
    # 3. start the container with sat credentials (what user do you need to be?)
    # 4. check if the container is running
    # 5. check if the container is listening on the port

    result = module_target_sat.execute('firewall-cmd --permanent --add-port="8080/tcp"')
    assert result.status == 0
    result = module_target_sat.execute('firewall-cmd --reload')
    assert result.status == 0
    yield module_target_sat
    result = module_target_sat.execute(f'podman pull {settings.mcp.registry}')
    assert result.status == 0
    result = module_target_sat.execute(
        f'podman run -it -p {settings.mcp.port}:8080 foreman-mcp-server --foreman-url https://{settings.server.hostname} --foreman-username {settings.mcp.username} --foreman-password {settings.mcp.password} --host {settings.mcp.hostname} --port {settings.mcp.port}'
    )
    assert result.status == 0
