"""
This module is to define pytest functions for content hosts

The functions in this module are read in the pytest_plugins/fixture_markers.py module
All functions in this module will be treated as fixtures that apply the contenthost mark
"""

from broker import Broker
import pytest

from robottelo import constants
from robottelo.config import settings
from robottelo.enums import NetworkType
from robottelo.hosts import ContentHost, Satellite


def host_conf(request):
    """A function that returns arguments for Broker host deployment"""
    conf = params = {}
    if hasattr(request, 'param'):
        params = request.param
    distro = params.get('distro', 'rhel')
    network = params.get('network')
    _rhelver = f"{distro}{params.get('rhel_version', settings.content_host.default_rhel_version)}"

    # check to see if no-containers is passed as an argument to pytest
    deploy_kwargs = {}
    if not any(
        [
            request.config.getoption('no_containers'),
            params.get('no_containers'),
            request.node.get_closest_marker('no_containers'),
        ]
    ):
        deploy_kwargs = settings.content_host.get(_rhelver).to_dict().get('container', {})
        if deploy_kwargs and network:
            deploy_kwargs.update({'Container': str(network)})
    # if we're not using containers or a container isn't available, use a VM
    if not deploy_kwargs:
        deploy_kwargs = settings.content_host.get(_rhelver).to_dict().get('vm', {})
        if network:
            deploy_kwargs.update({'deploy_network_type': network})
    if network:
        # pass the network type to the deploy kwargs, so the host class can use it
        deploy_kwargs.update({'net_type': network})
    conf.update(deploy_kwargs)
    return conf


@pytest.fixture
def rhel_contenthost(request):
    """A function-level fixture that provides a content host object parametrized"""
    # Request should be parametrized through pytest_fixtures.fixture_markers
    # unpack params dict
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture(scope='module')
def module_rhel_contenthost(request):
    """A module-level fixture that provides a content host object parametrized"""
    # Request should be parametrized through pytest_fixtures.fixture_markers
    # unpack params dict
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture(params=[{'rhel_version': '7'}])
def rhel7_contenthost(request):
    """A function-level fixture that provides a rhel7 content host object"""
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture(scope="class", params=[{'rhel_version': '7'}])
def rhel7_contenthost_class(request):
    """A fixture for use with unittest classes. Provides a rhel7 Content Host object"""
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture(scope='module', params=[{'rhel_version': '7'}])
def rhel7_contenthost_module(request):
    """A module-level fixture that provides a rhel7 content host object"""
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture(params=[{'rhel_version': '8'}])
def rhel8_contenthost(request):
    """A fixture that provides a rhel8 content host object"""
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture(scope='module', params=[{'rhel_version': '8'}])
def rhel8_contenthost_module(request):
    """A module-level fixture that provides a rhel8 content host object"""
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture(params=[{'rhel_version': '9'}])
def rhel9_contenthost(request):
    """A fixture that provides a rhel9 content host object"""
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        yield host


@pytest.fixture
def content_hosts(request):
    """A function-level fixture that provides two rhel content hosts object"""
    with Broker(**host_conf(request), host_class=ContentHost, _count=2) as hosts:
        hosts[0].set_infrastructure_type('physical')
        yield hosts


@pytest.fixture(scope='module')
def mod_content_hosts(request):
    """A module-level fixture that provides two rhel content hosts object"""
    with Broker(**host_conf(request), host_class=ContentHost, _count=2) as hosts:
        hosts[0].set_infrastructure_type('physical')
        yield hosts


@pytest.fixture
def katello_host_tools_host(target_sat, module_org, rhel_contenthost):
    """Register content host to Satellite and install katello-host-tools on the host."""
    repo = settings.repos['SATCLIENT_REPO'][f'RHEL{rhel_contenthost.os_version.major}']
    ak = target_sat.api.ActivationKey(
        content_view=module_org.default_content_view,
        max_hosts=100,
        organization=module_org,
        environment=target_sat.api.LifecycleEnvironment(id=module_org.library.id),
        auto_attach=True,
    ).create()
    rhel_contenthost.register(module_org, None, ak.name, target_sat, repo_data=f'repo={repo}')
    rhel_contenthost.install_katello_host_tools()
    return rhel_contenthost


@pytest.fixture
def cockpit_host(class_target_sat, class_org, rhel_contenthost):
    """Register content host to Satellite and install cockpit on the host."""
    rhelver = rhel_contenthost.os_version.major
    if rhelver > 7:
        repo = [settings.repos[f'rhel{rhelver}_os']['baseos']]
    else:
        repo = [settings.repos['rhel7_os'], settings.repos['rhel7_extras']]
    class_target_sat.register_host_custom_repo(class_org, rhel_contenthost, repo)
    rhel_contenthost.execute(f"hostnamectl set-hostname {rhel_contenthost.hostname} --static")
    rhel_contenthost.install_cockpit()
    rhel_contenthost.add_rex_key(satellite=class_target_sat)
    return rhel_contenthost


@pytest.fixture
def rex_contenthost(request, module_org, target_sat, module_ak_with_cv):
    request.param['no_containers'] = True
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        repo = settings.repos['SATCLIENT_REPO'][f'RHEL{host.os_version.major}']
        host.register(
            module_org, None, module_ak_with_cv.name, target_sat, repo_data=f'repo={repo}'
        )
        yield host


@pytest.fixture
def rex_contenthosts(request, module_org, target_sat, module_ak_with_cv):
    request.param['no_containers'] = True
    with Broker(**host_conf(request), host_class=ContentHost, _count=2) as hosts:
        for host in hosts:
            repo = settings.repos['SATCLIENT_REPO'][f'RHEL{host.os_version.major}']
            host.register(
                module_org, None, module_ak_with_cv.name, target_sat, repo_data=f'repo={repo}'
            )
        yield hosts


@pytest.fixture
def katello_host_tools_tracer_host(rex_contenthost, target_sat):
    """Install katello-host-tools-tracer and create custom repositories on the host.

    This fixture automatically configures IPv6 support based on the host's network type and creates
    version-appropriate repositories.

    :param rex_contenthost: Remote execution enabled content host
    :param target_sat: Target Satellite server
    :return: ContentHost with tracer tools installed and configured
    """
    # add IPv6 proxy for IPv6 communication based on network type
    if not rex_contenthost.network_type.has_ipv4:
        rex_contenthost.enable_ipv6_dnf_and_rhsm_proxy()
        rex_contenthost.enable_ipv6_system_proxy()

    # create a custom, rhel version-specific OS repo
    rhelver = rex_contenthost.os_version.major

    if rhelver > 7:
        # RHEL 8, 9 and 10 use the same repository structure
        rex_contenthost.create_custom_repos(**settings.repos[f'rhel{rhelver}_os'])
    else:
        # RHEL 7 has different repository structure
        rex_contenthost.create_custom_repos(
            **{f'rhel{rhelver}_os': settings.repos[f'rhel{rhelver}_os']}
        )

    rex_contenthost.install_tracer()
    return rex_contenthost


@pytest.fixture
def rhel_contenthost_with_repos(request, target_sat):
    """Install katello-host-tools-tracer, create custom
    repositories on the host"""
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        # add IPv6 proxy for IPv6 communication
        if not host.network_type.has_ipv4:
            host.enable_ipv6_dnf_and_rhsm_proxy()
            host.enable_ipv6_system_proxy()

        # create a custom, rhel version-specific OS repo
        rhelver = host.os_version.major
        if rhelver > 7:
            host.create_custom_repos(**settings.repos[f'rhel{rhelver}_os'])
        else:
            host.create_custom_repos(**{f'rhel{rhelver}_os': settings.repos[f'rhel{rhelver}_os']})
        yield host


@pytest.fixture(scope='module')
def module_container_contenthost(request, module_target_sat, module_org, module_activation_key):
    """Fixture that installs docker on the content host"""
    request.param = {
        "rhel_version": "8",
        "distro": "rhel",
        "no_containers": True,
        "network": "ipv6" if module_target_sat.network_type == NetworkType.IPV6 else "ipv4",
    }
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        host.register_to_cdn()
        for client in settings.container.clients:
            assert host.execute(f'yum -y install {client}').status == 0, (
                f'{client} installation failed'
            )
        assert host.execute('systemctl enable --now podman').status == 0
        assert host.execute('yum -y install expect').status == 0
        host.unregister()
        assert (
            host.register(module_org, None, module_activation_key.name, module_target_sat).status
            == 0
        )
        yield host


@pytest.fixture(scope='module')
def module_flatpak_contenthost(request):
    assert request.param['rhel_version'] > 8, 'Unsupported RHEL version'
    request.param['no_containers'] = True
    with Broker(**host_conf(request), host_class=ContentHost) as host:
        host.register_to_cdn()
        res = host.execute('dnf -y install podman flatpak dbus-x11')
        assert res.status == 0, f'Initial installation failed: {res.stderr}'
        host.unregister()
        yield host


@pytest.fixture
def centos_host(request, version):
    request.param = {
        "rhel_version": version.split('.')[0],
        "distro": "centos",
        "no_containers": True,
    }
    with Broker(
        **host_conf(request),
        host_class=ContentHost,
        deploy_network_type=settings.content_host.network_type,
    ) as host:
        yield host


@pytest.fixture
def oracle_host(request, version):
    request.param = {
        "rhel_version": version.split('.')[0],
        "distro": "oracle",
        "no_containers": True,
    }
    with Broker(
        **host_conf(request),
        host_class=ContentHost,
        deploy_network_type=settings.content_host.network_type,
    ) as host:
        yield host


@pytest.fixture
def bootc_host():
    """Fixture to check out boot-c host"""
    with Broker(
        workflow='deploy-bootc',
        host_class=ContentHost,
        target_template='tpl-bootc-rhel-10.0',
        # TODO(sbible): Check whether this is valid for dualstack scenaro
        deploy_network_type='ipv6' if settings.server.network_type == NetworkType.IPV6 else 'ipv4',
    ) as host:
        assert (
            host.execute(
                f"echo '{constants.DUMMY_BOOTC_FACTS}' > /etc/rhsm/facts/bootc.facts"
            ).status
            == 0
        )
        yield host


@pytest.fixture(scope='module', params=[{'rhel_version': 8, 'no_containers': True}])
def external_puppet_server(request):
    deploy_args = host_conf(request)
    deploy_args['target_cores'] = 2
    deploy_args['target_memory'] = '4GiB'
    with Broker(**deploy_args, host_class=ContentHost) as host:
        host.register_to_cdn()
        # Install puppet packages
        assert (
            host.execute(
                'dnf install -y https://yum.puppet.com/puppet-release-el-8.noarch.rpm'
            ).status
            == 0
        )
        assert host.execute('dnf install -y puppetserver').status == 0
        # Source puppet profiles
        host.execute('. /etc/profile.d/puppet-agent.sh')
        # Setup Puppet Server CA
        assert host.execute('puppetserver ca setup').status == 0
        # Set puppet server as $HOSTNAME
        assert host.execute('puppet config set server $HOSTNAME').status == 0
        assert host.hostname in host.execute('puppet config print server').stdout
        # Enable service and setup firewall for puppetserver
        assert host.execute('systemctl enable --now puppetserver').status == 0
        assert host.execute('firewall-cmd --permanent --add-port="8140/tcp"').status == 0
        assert host.execute('firewall-cmd --reload').status == 0
        # Install theforeman/motd puppet module
        puppet_prod_env = '/etc/puppetlabs/code/environments/production'
        host.execute('puppet module install theforeman/motd')
        host.execute(f'mkdir -p {puppet_prod_env}/manifests')
        host.execute(f'echo "include motd" > {puppet_prod_env}/manifests/site.pp')

        yield host


@pytest.fixture(scope="module")
def sat_upgrade_chost():
    """A module-level fixture that provides a UBI_8 content host for upgrade scenario testing"""
    return Broker(
        container_host=settings.content_host.rhel8.container.container_host, host_class=ContentHost
    ).checkout()


@pytest.fixture
def custom_host(request):
    """A rhel content host that passes custom host config through request.param"""
    deploy_args = request.param
    # if 'deploy_rhel_version' is not set, let's default to what's in content_host.yaml
    deploy_args['deploy_rhel_version'] = deploy_args.get(
        'deploy_rhel_version', settings.content_host.default_rhel_version
    )
    deploy_args['workflow'] = 'deploy-rhel'
    with Broker(**deploy_args, host_class=Satellite) as host:
        yield host
