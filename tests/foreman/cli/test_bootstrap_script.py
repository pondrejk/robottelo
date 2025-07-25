"""Test for bootstrap script (bootstrap.py)

:Requirement: Bootstrap Script

:CaseAutomation: Automated

:CaseComponent: Bootstrap

:Team: Phoenix-subscriptions

:CaseImportance: High

"""

import pytest

from robottelo.config import settings


@pytest.mark.e2e
@pytest.mark.pit_server
@pytest.mark.pit_client
@pytest.mark.rhel_ver_list([settings.content_host.default_rhel_version])
def test_positive_register(
    module_org,
    module_location,
    module_lce,
    module_ak_cv_lce,
    module_published_cv,
    target_sat,
    rhel_contenthost,
):
    """System is registered

    :id: e34561fd-e0d6-4587-84eb-f86bd131aab1

    :steps:

        1. Ensure system is not registered
        2. Register a system
        3. Ensure system is registered
        4. Register system once again


    :expectedresults: system is registered, host is created

    :CaseAutomation: Automated

    :CaseImportance: Critical

    :customerscenario: true

    :BZ: 2001476
    """
    # Workaround for a bug in bootstrap.py https://github.com/Katello/katello-client-bootstrap/pull/373
    # rhel_contenthost has internet-based repos enabled, which it can't reach in IPv6-only setups,
    # but also shouldn't have configured to begin with.
    rhel_contenthost.enable_ipv6_dnf_and_rhsm_proxy()
    if rhel_contenthost.os_version.major == 7:
        python_cmd = 'python'
    elif rhel_contenthost.os_version.major == 8:
        python_cmd = '/usr/libexec/platform-python'
    else:
        python_cmd = 'python3'
    hg = target_sat.api.HostGroup(location=[module_location], organization=[module_org]).create()
    # assure system is not registered
    result = rhel_contenthost.execute('subscription-manager identity')
    # result will be 1 if not registered
    assert result.status == 1
    assert rhel_contenthost.execute(
        f'curl -o /root/bootstrap.py "http://{target_sat.hostname}/pub/bootstrap.py" '
    )
    assert rhel_contenthost.execute(
        f'{python_cmd} /root/bootstrap.py -s {target_sat.hostname} -o {module_org.name}'
        f' -L {module_location.name} -a {module_ak_cv_lce.name} --hostgroup={hg.name}'
        ' --skip puppet --skip foreman'
    )
    # assure system is registered
    result = rhel_contenthost.execute('subscription-manager identity')
    # result will be 0 if registered
    assert result.status == 0
    # register system once again
    assert rhel_contenthost.execute(
        f'{python_cmd} /root/bootstrap.py -s "{target_sat.hostname}" -o {module_org.name} '
        f'-L {module_location.name} -a {module_ak_cv_lce.name} --hostgroup={hg.name}'
        '--skip puppet --skip foreman '
    )
    # assure system is registered
    result = rhel_contenthost.execute('subscription-manager identity')
    # result will be 0 if registered
    assert result.status == 0
