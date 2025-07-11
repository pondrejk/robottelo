"""Tests for registration.

:Requirement: Registration

:CaseComponent: Registration

:CaseAutomation: Automated

:CaseImportance: High

:Team: Phoenix-subscriptions
"""

import pytest

from robottelo.config import settings

pytestmark = pytest.mark.destructive


@pytest.mark.no_containers
@pytest.mark.pit_client
@pytest.mark.rhel_ver_match('[^6]')
def test_host_registration_rex_pull_mode(
    module_org,
    module_satellite_mqtt,
    module_location,
    module_ak_with_cv,
    module_capsule_configured_mqtt,
    rhel_contenthost_with_repos,
):
    """Verify content host registration with Satellite/Capsule as MQTT broker

    :id: a082f599-fbf7-4779-aa18-5139e2bce779

    :expectedresults: Host registered successfully with MQTT broker

    :parametrized: yes
    """
    client = rhel_contenthost_with_repos
    org = module_org
    client_repo = settings.repos.SATCLIENT_REPO[f'rhel{client.os_version.major}']
    # register host to satellite with pull provider rex
    result = client.api_register(
        module_satellite_mqtt,
        organization=org,
        location=module_location,
        activation_keys=[module_ak_with_cv.name],
        setup_remote_execution_pull=True,
        repo=client_repo,
    )
    assert result.status == 0, f'Failed to register host: {result.stderr}'

    # check mqtt client is running

    service_name = client.get_yggdrasil_service_name()
    result = client.execute(f'systemctl status {service_name}')
    assert result.status == 0, f'Failed to start yggdrasil on client: {result.stderr}'
    mqtt_url = f'mqtts://{module_satellite_mqtt.hostname}:1883'
    assert client.execute(f'cat /etc/yggdrasil/config.toml | grep {mqtt_url}').status == 0

    # Update module_capsule_configured_mqtt to include module_org/module_location
    nc = module_capsule_configured_mqtt.nailgun_smart_proxy
    module_satellite_mqtt.api.SmartProxy(id=nc.id, organization=[org]).update(['organization'])
    module_satellite_mqtt.api.SmartProxy(id=nc.id, location=[module_location]).update(['location'])

    # register host to capsule with pull provider rex
    result = client.api_register(
        module_satellite_mqtt,
        smart_proxy=nc,
        organization=org,
        location=module_location,
        activation_keys=[module_ak_with_cv.name],
        setup_remote_execution_pull=True,
        repo=client_repo,
        force=True,
    )
    assert result.status == 0, f'Failed to register host: {result.stderr}'

    # check mqtt client is running
    result = client.execute(f'systemctl status {service_name}')
    assert result.status == 0, f'Failed to start yggdrasil on client: {result.stderr}'
    new_mqtt_url = f'mqtts://{module_capsule_configured_mqtt.hostname}:1883'
    assert client.execute(f'cat /etc/yggdrasil/config.toml | grep {new_mqtt_url}').status == 0
    # After force register existing config.toml is saved as backup
    assert client.execute(f'cat /etc/yggdrasil/config.toml.bak | grep {mqtt_url}').status == 0
