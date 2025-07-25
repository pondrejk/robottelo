"""Test class for converting to RHEL from API

:Requirement: Convert2rhel

:CaseAutomation: Automated

:CaseComponent: Conversionsappliance

:CaseImportance: Critical

:Team: Rocket

"""

import json

import pytest
import requests

from robottelo.config import settings
from robottelo.constants import DEFAULT_ARCHITECTURE, REPOS
from robottelo.utils.issue_handlers import is_open


def create_repo(sat, org, repo_url, ssl_cert=None):
    """Create and sync repository"""
    product = sat.api.Product(organization=org).create()
    options = {
        'organization': org,
        'product': product,
        'content_type': 'yum',
        'url': repo_url,
        'ssl_ca_cert': ssl_cert,
        'unprotected': True,
        'verify_ssl_on_sync': False,
    }
    repo = sat.api.Repository(**options).create()
    repo.product = product
    repo.sync()
    return repo


def update_cv(sat, cv, lce, repos):
    """Update and publish Content view with repos"""
    cv = sat.api.ContentView(id=cv.id, repository=repos).update(['repository'])
    cv.publish()
    cv = cv.read()
    cv.version.sort(key=lambda version: version.id)
    cv.version[-1].promote(data={'environment_ids': lce.id, 'force': False})
    return cv


@pytest.fixture(scope='module')
def ssl_cert(module_target_sat, module_els_sca_manifest_org):
    """Create credential with SSL cert for Oracle Linux"""
    res = requests.get(settings.repos.convert2rhel.ssl_cert_oracle)
    res.raise_for_status()
    return module_target_sat.api.ContentCredential(
        content=res.text, organization=module_els_sca_manifest_org, content_type='cert'
    ).create()


@pytest.fixture
def activation_key_rhel(
    module_target_sat, module_els_sca_manifest_org, module_lce, module_promoted_cv
):
    """Create activation key that will be used after conversion for registration"""
    return module_target_sat.api.ActivationKey(
        organization=module_els_sca_manifest_org,
        content_view=module_promoted_cv,
        environment=module_lce,
    ).create()


@pytest.fixture(scope='module')
def enable_rhel_subscriptions(module_target_sat, module_els_sca_manifest_org, version):
    """Enable and sync RHEL rpms repos"""
    major = version.split('.')[0]
    minor = ''
    if major == '8':
        repo_names = ['rhel8_bos', 'rhel8_aps']
        minor = version[1:]
    else:
        repo_names = ['rhel7_els']

    rh_repos = []
    tasks = []
    for name in repo_names:
        rh_repo_id = module_target_sat.api_factory.enable_rhrepo_and_fetchid(
            basearch=DEFAULT_ARCHITECTURE,
            org_id=module_els_sca_manifest_org.id,
            product=REPOS[name]['product'],
            repo=REPOS[name]['name'] + minor,
            reposet=REPOS[name]['reposet'],
            releasever=REPOS[name]['releasever'] + minor,
        )
        # Sync step because repo is not synced by default
        rh_repo = module_target_sat.api.Repository(id=rh_repo_id).read()
        task = rh_repo.sync(synchronous=False)
        tasks.append(task)
        rh_repos.append(rh_repo)
    for task in tasks:
        module_target_sat.wait_for_tasks(
            search_query=(f'id = {task["id"]}'),
            poll_timeout=2500,
            search_rate=20,
            max_tries=10,
        )
        task_status = module_target_sat.api.ForemanTask(id=task['id']).poll()
        assert task_status['result'] == 'success'
    return rh_repos


@pytest.fixture
def centos(
    module_target_sat,
    centos_host,
    module_els_sca_manifest_org,
    smart_proxy_location,
    module_promoted_cv,
    module_lce,
    version,
    enable_rhel_subscriptions,
):
    """Deploy and register Centos host"""
    major = version.split('.')[0]
    centos_host.enable_ipv6_dnf_proxy()
    assert centos_host.execute('yum -y update').status == 0
    repo_url = settings.repos.convert2rhel.convert_to_rhel_repo.format(major)
    repo = create_repo(module_target_sat, module_els_sca_manifest_org, repo_url)
    cv = update_cv(
        module_target_sat, module_promoted_cv, module_lce, enable_rhel_subscriptions + [repo]
    )
    ak = module_target_sat.api.ActivationKey(
        organization=module_els_sca_manifest_org,
        content_view=cv,
        environment=module_lce,
    ).create()
    # Ensure C2R repo is enabled in the activation key
    all_content = ak.product_content(data={'content_access_mode_all': '1'})['results']
    repo_label = [content['label'] for content in all_content if content['name'] == repo.name][0]
    ak.content_override(data={'content_overrides': [{'content_label': repo_label, 'value': '1'}]})

    # Register CentOS host with Satellite
    result = centos_host.api_register(
        module_target_sat,
        organization=module_els_sca_manifest_org,
        activation_keys=[ak.name],
        location=smart_proxy_location,
    )
    assert result.status == 0, f'Failed to register host: {result.stderr}'

    if centos_host.execute('needs-restarting -r').status == 1:
        centos_host.power_control(state='reboot')

    yield centos_host
    # close ssh session before teardown, because of reboot in conversion it may cause problems
    centos_host.close()


@pytest.fixture
def oracle(
    module_target_sat,
    oracle_host,
    module_els_sca_manifest_org,
    smart_proxy_location,
    module_promoted_cv,
    module_lce,
    ssl_cert,
    version,
    enable_rhel_subscriptions,
):
    """Deploy and register Oracle host"""
    major = version.split('.')[0]
    oracle_host.enable_ipv6_dnf_proxy()
    # disable rhn-client-tools because it obsoletes the subscription manager package
    oracle_host.execute('echo "exclude=rhn-client-tools" >> /etc/yum.conf')
    # Install and set correct RHEL compatible kernel and using non-UEK kernel, based on C2R docs
    assert (
        oracle_host.execute(
            'yum install -y kernel && '
            'grubby --set-default /boot/vmlinuz-'
            '`rpm -q --qf "%{BUILDTIME}\t%{EVR}.%{ARCH}\n" kernel | sort -nr | head -1 | cut -f2`'
        ).status
        == 0
    )
    assert oracle_host.execute('yum -y update').status == 0

    if major == '8':
        # needs-restarting missing in OEL8
        assert oracle_host.execute('dnf install -y yum-utils').status == 0
        # Fix inhibitor CHECK_FIREWALLD_AVAILABILITY::FIREWALLD_MODULES_CLEANUP_ON_EXIT_CONFIG -
        # Firewalld is set to cleanup modules after exit
        result = oracle_host.execute(
            'sed -i -- "s/CleanupModulesOnExit=yes/CleanupModulesOnExit=no/g" '
            '/etc/firewalld/firewalld.conf && firewall-cmd --reload'
        )
        assert result.status == 0

        # Set RHEL kernel to be used during boot
        oracle_host.execute("mkdir -p /boot/loader/entries/backup")
        oracle_host.execute("mv /boot/loader/entries/*uek*.conf /boot/loader/entries/backup/")
        # Needs reboot to reflect the changes
        oracle_host.power_control(state='reboot')
        assert oracle_host.execute("grubby --default-kernel | grep uek").status != 0
        assert oracle_host.execute("uname -r | grep uek").status != 0

        # Fix inhibitor TAINTED_KMODS::TAINTED_KMODS_DETECTED - Tainted kernel modules detected
        blacklist_cfg = '/etc/modprobe.d/blacklist.conf'
        assert oracle_host.execute('modprobe -r nvme_tcp').status == 0
        assert oracle_host.execute(f'echo "blacklist nvme_tcp" >> {blacklist_cfg}').status == 0
        assert (
            oracle_host.execute(f'echo "install nvme_tcp /bin/false" >> {blacklist_cfg}').status
            == 0
        )

    if oracle_host.execute('needs-restarting -r').status == 1:
        oracle_host.power_control(state='reboot')

    repo_url = settings.repos.convert2rhel.convert_to_rhel_repo.format(major)
    repo = create_repo(module_target_sat, module_els_sca_manifest_org, repo_url, ssl_cert)
    cv = update_cv(
        module_target_sat, module_promoted_cv, module_lce, enable_rhel_subscriptions + [repo]
    )
    ak = module_target_sat.api.ActivationKey(
        organization=module_els_sca_manifest_org,
        content_view=cv,
        environment=module_lce,
    ).create()
    # Ensure C2R repo is enabled in the activation key
    all_content = ak.product_content(data={'content_access_mode_all': '1'})['results']
    repo_label = [content['label'] for content in all_content if content['name'] == repo.name][0]
    ak.content_override(data={'content_overrides': [{'content_label': repo_label, 'value': '1'}]})

    # UBI repo required for subscription-manager packages on Oracle
    ubi_url = settings.repos.convert2rhel.ubi7 if major == '7' else settings.repos.convert2rhel.ubi8

    # Register Oracle host with Satellite
    result = oracle_host.api_register(
        module_target_sat,
        organization=module_els_sca_manifest_org,
        activation_keys=[ak.name],
        location=smart_proxy_location,
        repo=ubi_url,
    )
    assert result.status == 0, f'Failed to register host: {result.stderr}'

    yield oracle_host
    # close ssh session before teardown, because of reboot in conversion it may cause problems
    oracle_host.close()


@pytest.fixture(scope='module')
def version(request):
    """Version of converted OS"""
    return settings.content_host.get(request.param).vm.deploy_rhel_version


@pytest.mark.e2e
@pytest.mark.parametrize('version', ['oracle7', 'oracle8'], indirect=True)
def test_convert2rhel_oracle_with_pre_conversion_template_check(
    module_target_sat, oracle, activation_key_rhel, version
):
    """Convert Oracle linux to RHEL

    :id: 7fd393f0-551a-4de0-acdd-7f026b485f79

    :steps:
        0. Have host registered to Satellite
        1. Check for operating system
        2. Convert host to RHEL

    :expectedresults: Host is converted to RHEL with correct os facts
        and subscription status

    :parametrized: yes

    :Verifies: SAT-24654, SAT-24655, SAT-26076
    """
    major = version.split('.')[0]
    host_content = module_target_sat.api.Host(id=oracle.hostname).read_json()
    assert host_content['operatingsystem_name'] == f"OracleLinux {version}"

    # Pre-conversion template job
    template_id = (
        module_target_sat.api.JobTemplate()
        .search(query={'search': 'name="Convert2RHEL analyze"'})[0]
        .id
    )
    job = module_target_sat.api.JobInvocation().run(
        synchronous=False,
        data={
            'job_template_id': template_id,
            'targeting_type': 'static_query',
            'search_query': f'name = {oracle.hostname}',
            'inputs': {
                'ELS': 'yes' if major <= '7' else 'no',
            },
        },
    )
    # wait for job to complete
    module_target_sat.wait_for_tasks(
        f'resource_type = JobInvocation and resource_id = {job["id"]}',
        poll_timeout=5500,
        search_rate=20,
    )
    result = module_target_sat.api.JobInvocation(id=job['id']).read()
    assert result.succeeded == 1
    # execute job 'Convert 2 RHEL' on host
    template_id = (
        module_target_sat.api.JobTemplate().search(query={'search': 'name="Convert to RHEL"'})[0].id
    )
    job = module_target_sat.api.JobInvocation().run(
        synchronous=False,
        data={
            'job_template_id': template_id,
            'inputs': {
                'Activation Key': activation_key_rhel.id,
                'Restart': 'yes',
                'ELS': 'yes' if major <= '7' else 'no',
            },
            'targeting_type': 'static_query',
            'search_query': f'name = {oracle.hostname}',
        },
    )
    # wait for job to complete
    module_target_sat.wait_for_tasks(
        f'resource_type = JobInvocation and resource_id = {job["id"]}', poll_timeout=2500
    )
    result = module_target_sat.api.JobInvocation(id=job['id']).read()
    assert result.succeeded == 1

    # check facts: correct os and valid subscription status
    host_content = module_target_sat.api.Host(id=oracle.hostname).read_json()
    # workaround for BZ 2080347
    assert (
        host_content['operatingsystem_name'].startswith(f'RHEL Server {version}')
        or host_content['operatingsystem_name'].startswith(f'RedHat {version}')
        or host_content['operatingsystem_name'].startswith(f'RHEL {version}')
    )
    # Wait for the host to be rebooted and SSH daemon to be started.
    oracle.wait_for_connection()

    # Verify convert2rhel facts are generated, and verify fact conversions.success is true
    assert host_content['facts']['conversions::success'] == 'true'
    convert2rhel_facts = json.loads(oracle.execute('cat /etc/rhsm/facts/convert2rhel.facts').stdout)
    assert convert2rhel_facts['conversions.env.CONVERT2RHEL_THROUGH_FOREMAN'] == '1'
    # https://issues.redhat.com/browse/RHELC-1737
    target_os_name = 'Oracle Linux Server' if is_open('RHELC-1737') else 'Red Hat'
    assert target_os_name in convert2rhel_facts['conversions.target_os.name']
    assert convert2rhel_facts['conversions.success'] is True


@pytest.mark.e2e
@pytest.mark.parametrize('version', ['centos7', 'centos8'], indirect=True)
def test_convert2rhel_centos_with_pre_conversion_template_check(
    module_target_sat, centos, activation_key_rhel, version
):
    """Convert CentOS linux to RHEL

    :id: 6f698440-7d85-4deb-8dd9-363ea9003b92

    :steps:
        0. Have host registered to Satellite
        1. Check for operating system
        2. Convert host to RHEL

    :expectedresults: Host is converted to RHEL with correct os facts
        and subscription status

    :parametrized: yes

    :Verifies: SAT-24654, SAT-24655, SAT-26076
    """
    host_content = module_target_sat.api.Host(id=centos.hostname).read_json()
    major = version.split('.')[0]
    assert host_content['operatingsystem_name'] == f'CentOS {major}'

    # Pre-conversion template job
    template_id = (
        module_target_sat.api.JobTemplate()
        .search(query={'search': 'name="Convert2RHEL analyze"'})[0]
        .id
    )
    job = module_target_sat.api.JobInvocation().run(
        synchronous=False,
        data={
            'job_template_id': template_id,
            'targeting_type': 'static_query',
            'search_query': f'name = {centos.hostname}',
            'inputs': {
                'ELS': 'yes' if major <= '7' else 'no',
            },
        },
    )
    # wait for job to complete
    module_target_sat.wait_for_tasks(
        f'resource_type = JobInvocation and resource_id = {job["id"]}',
        poll_timeout=5500,
        search_rate=20,
    )
    result = module_target_sat.api.JobInvocation(id=job['id']).read()
    assert result.succeeded == 1

    # execute job 'Convert 2 RHEL' on host
    template_id = (
        module_target_sat.api.JobTemplate().search(query={'search': 'name="Convert to RHEL"'})[0].id
    )
    job = module_target_sat.api.JobInvocation().run(
        synchronous=False,
        data={
            'job_template_id': template_id,
            'inputs': {
                'Activation Key': activation_key_rhel.id,
                'Restart': 'yes',
                'ELS': 'yes' if major <= '7' else 'no',
            },
            'targeting_type': 'static_query',
            'search_query': f'name = {centos.hostname}',
        },
    )
    # wait for job to complete
    module_target_sat.wait_for_tasks(
        f'resource_type = JobInvocation and resource_id = {job["id"]}',
        poll_timeout=2500,
        search_rate=20,
    )
    result = module_target_sat.api.JobInvocation(id=job['id']).read()
    assert result.succeeded == 1

    # check facts: correct os and valid subscription status
    host_content = module_target_sat.api.Host(id=centos.hostname).read_json()
    # workaround for BZ 2080347
    assert (
        host_content['operatingsystem_name'].startswith(f'RHEL Server {version}')
        or host_content['operatingsystem_name'].startswith(f'RedHat {version}')
        or host_content['operatingsystem_name'].startswith(f'RHEL {version}')
    )

    # Wait for the host to be rebooted and SSH daemon to be started.
    centos.wait_for_connection()

    # Verify convert2rhel facts are generated, and verify fact conversions.success is true
    assert host_content['facts']['conversions::success'] == 'true'
    convert2rhel_facts = json.loads(centos.execute('cat /etc/rhsm/facts/convert2rhel.facts').stdout)
    assert convert2rhel_facts['conversions.env.CONVERT2RHEL_THROUGH_FOREMAN'] == '1'
    # https://issues.redhat.com/browse/RHELC-1737
    target_os_name = 'CentOS Linux' if is_open('RHELC-1737') else 'Red Hat'
    assert target_os_name in convert2rhel_facts['conversions.target_os.name']
    assert convert2rhel_facts['conversions.success'] is True
