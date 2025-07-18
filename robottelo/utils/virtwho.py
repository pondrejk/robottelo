"""Utility module to handle the virtwho configure UI/CLI/API testing"""

import json
import re
import uuid

from fauxfactory import gen_integer, gen_string, gen_url
from nailgun import entities
import requests
from wait_for import wait_for

from robottelo import ssh
from robottelo.cli.base import Base
from robottelo.cli.host import Host
from robottelo.cli.virt_who_config import VirtWhoConfig
from robottelo.config import settings
from robottelo.constants import DEFAULT_ORG

ETC_VIRTWHO_CONFIG = "/etc/virt-who.conf"


class VirtWhoError(Exception):
    """Exception raised for failed virtwho operations"""


def _parse_entry(entry):
    """Parse the string and return json format"""
    try:
        return json.loads(entry)
    except json.decoder.JSONDecodeError:
        return None


def get_system(system_type):
    """Return a dict account for ssh connect.

    :param str system_type: The type of the system, should be one of
        ('satellite', 'esx', 'xen', 'hyperv', 'rhevm', 'libvirt', 'kubevirt', 'ahv').
    :raises: VirtWhoError: If wrong ``system_type`` specified.
    """
    hypervisor_list = ['esx', 'xen', 'hyperv', 'rhevm', 'libvirt', 'kubevirt', 'ahv']
    system_type_list = ['satellite']
    system_type_list.extend(hypervisor_list)
    if system_type in hypervisor_list:
        return {
            'hostname': getattr(settings.virtwho, system_type).guest,
            'username': getattr(settings.virtwho, system_type).guest_username,
            'password': getattr(settings.virtwho, system_type).guest_password,
            'port': getattr(settings.virtwho, system_type).guest_port,
        }
    if system_type == 'satellite':
        return {
            'hostname': settings.server.hostname,
            'username': settings.server.ssh_username,
            'password': settings.server.ssh_password,
        }
    raise VirtWhoError(
        f'"{system_type}" system type is not supported. Please use one of {system_type_list}'
    )


def get_guest_info(hypervisor_type):
    """Return the guest_name, guest_uuid"""
    _, guest_name = runcmd('hostname', system=get_system(hypervisor_type))
    _, guest_uuid = runcmd('dmidecode -s system-uuid', system=get_system(hypervisor_type))
    if not guest_uuid or not guest_name:
        raise VirtWhoError(f'Failed to get the guest info for {hypervisor_type}')
    # Different UUID for vcenter by dmidecode and vcenter MOB
    if hypervisor_type == 'esx':
        guest_uuid = guest_uuid.split('-')[-1]
    if hypervisor_type == 'hyperv':
        guest_uuid = guest_uuid.split('-')[-1].upper()
    return guest_name, guest_uuid


def runcmd(cmd, system=None, timeout=600000, output_format='base'):
    """Return the retcode and stdout.

    :param str cmd: The command line will be executed in the target system.
    :param dict system: the system account which ssh will connect to,
        it will connect to the satellite host if the system is None.
    :param int timeout: Time to wait for establish the connection.
    :param str output_format: base|json|csv|list
    """
    system = system or get_system('satellite')
    result = ssh.command(cmd, **system, timeout=timeout, output_format=output_format)
    return result.status, result.stdout.strip()


def register_system(system, activation_key=None, org='Default_Organization', env='Library'):
    """Return True if the system is registered to satellite successfully.

    :param dict system: system account used by ssh to connect and register.
    :param str activation_key: the activation key will be used to register.
    :param str org: Which organization will be used to register.
    :param str env: Which environment will be used to register.
    :raises: VirtWhoError: If failed to register the system.
    """
    runcmd('subscription-manager unregister', system)
    runcmd('subscription-manager clean', system)
    runcmd('rpm -qa | grep katello-ca-consumer | xargs rpm -e |sort', system)
    runcmd(
        f'rpm -ihv http://{settings.server.hostname}/pub/katello-ca-consumer-latest.noarch.rpm',
        system,
    )
    cmd = f'subscription-manager register --org={org} --environment={env} '
    if activation_key is not None:
        cmd += f'--activationkey={activation_key}'
    else:
        cmd += f'--username={settings.server.admin_username} --password={settings.server.admin_password}'
    ret, stdout = runcmd(cmd, system)
    if ret == 0 or "system has been registered" in stdout:
        return True
    raise VirtWhoError(f'Failed to register system: {system}')


def virtwho_cleanup():
    """Before running test cases, need to clean the environment.
    Do the following:
    1. stop virt-who service.
    2. kill all the virt-who pid
    3. clean rhsm.log message, make sure there is no old message exist.
    4. clean all the configure files in /etc/virt-who.d/
    """
    runcmd("systemctl stop virt-who")
    runcmd("pkill -9 virt-who")
    runcmd("rm -f /var/run/virt-who.pid")
    runcmd("rm -f /var/log/rhsm/rhsm.log")
    runcmd("rm -rf /etc/virt-who.d/*")
    runcmd("rm -rf /tmp/deploy_script.sh")


def get_virtwho_status():
    """Return the status of virt-who service, it will help us to know
    the virt-who configuration file is deployed or not.
    """
    _, logs = runcmd('cat /var/log/rhsm/rhsm.log')
    error = len(re.findall(r'\[.*ERROR.*\]', logs))
    ret, stdout = runcmd('systemctl status virt-who')
    running_stauts = ['is running', 'Active: active (running)']
    stopped_status = ['is stopped', 'Active: inactive (dead)']
    if ret != 0:
        return 'undefined'
    if error != 0:
        return 'logerror'
    if any(key in stdout for key in running_stauts):
        return 'running'
    if any(key in stdout for key in stopped_status):
        return 'stopped'
    return 'undefined'


def get_configure_id(name):
    """Return the configure id by hammer.
    :param str name: the configure name you have created.
    :raises: VirtWhoError: If failed to get the configure info by hammer.
    """
    config = VirtWhoConfig.info({'name': name})
    if 'id' in config['general-information']:
        return config['general-information']['id']
    raise VirtWhoError(f"No configure id found for {name}")


def get_configure_command(config_id, org=DEFAULT_ORG):
    """Return the deploy command line based on configure id.
    :param str config_id: the unique id of the configure file you have created.
    :param str org: the satellite organization name.
    """
    username, password = Base._get_username_password()
    return f"hammer -u {username} -p {password} virt-who-config deploy --id {config_id} --organization '{org}' "


def get_configure_file(config_id):
    """Return the configuration file full name in /etc/virt-who.d
    :param str config_id: the unique id of the configuration file you have created.
    """
    return f"/etc/virt-who.d/virt-who-config-{config_id}.conf"


def get_configure_option(option, filename):
    """Return the option's value for the specific file.

    :param str option: the option name in the configuration file
    :param str filename: the configuration file, it could be:
        /etc/sysconfig/virt-who
        /etc/virt-who.d/virt-who-config-{}.conf
    :raises: VirtWhoError: If this option name not in the file.
    """
    cmd = f"grep -v '^#' {filename} | grep ^{option}"
    ret, stdout = runcmd(cmd)
    if ret == 0 and option in stdout:
        return stdout.split('=')[1].strip()
    raise VirtWhoError(f"option {option} is not exist or not be enabled in {filename}")


def get_rhsm_log():
    """
    Return the content of log file /var/log/rhsm/rhsm.log
    """
    _, logs = runcmd('cat /var/log/rhsm/rhsm.log')
    return logs


def check_message_in_rhsm_log(message):
    """Check the message exist in /var/log/rhsm/rhsm.log"""
    wait_for(
        lambda: 'Host-to-guest mapping being sent to' in get_rhsm_log(),
        timeout=20,
        delay=2,
    )
    logs = get_rhsm_log()
    return any(message in line for line in logs.split('\n'))


def _get_hypervisor_mapping(hypervisor_type):
    """Analysing rhsm.log and get to know: what is the hypervisor_name
    for the specific guest.
    :param str logs: the output of rhsm.log.
    :param str hypervisor_type: esx, libvirt, rhevm, xen, libvirt, kubevirt, ahv
    :raises: VirtWhoError: If hypervisor_name is None.
    :return: hypervisor_name and guest_name
    """
    wait_for(
        lambda: 'Host-to-guest mapping being sent to' in get_rhsm_log(),
        timeout=20,
        delay=2,
    )
    logs = get_rhsm_log()
    mapping = list()
    entry = None
    guest_name, guest_uuid = get_guest_info(hypervisor_type)
    for line in logs.split('\n'):
        if not line:
            continue
        if line[0].isdigit():
            if entry:
                mapping.append(_parse_entry(entry))
            entry = '{'
            continue
        if entry:
            entry += line
    else:
        mapping.append(_parse_entry(entry))
    mapping = [_ for _ in mapping if _ is not None]
    # Always check the last json section to get the hypervisorId
    for item in mapping[-1]['hypervisors']:
        for guest in item['guestIds']:
            if guest_uuid in guest['guestId']:
                hypervisor_name = item['hypervisorId']['hypervisorId']
                break
    if hypervisor_name:
        return hypervisor_name, guest_name
    raise VirtWhoError(f"Failed to get the hypervisor_name for guest {guest_name}")


def get_hypervisor_ahv_mapping(hypervisor_type):
    """Analysing rhsm.log and get to know: if ahv guest and host report in rhsm.log.
    :param str logs: the output of rhsm.log.
    :param str hypervisor_type: ahv
    :param str system_uuid: the uuid of the ahv host
    :raises: VirtWhoError: If message is not found.
    :return: True or False
    """
    wait_for(
        lambda: 'Successfully logged into the AHV REST server' in get_rhsm_log(),
        timeout=10,
        delay=2,
    )
    logs = get_rhsm_log()
    mapping = list()
    entry = None
    guest_name, guest_uuid = get_guest_info(hypervisor_type)
    for line in logs.split('\n'):
        if not line:
            continue
        if line[0].isdigit():
            if entry:
                mapping.append(_parse_entry(entry))
            entry = '{'
            continue
        if entry:
            entry += line
    else:
        mapping.append(_parse_entry(entry))
    mapping = [_ for _ in mapping if _ is not None]
    # Always check the last json section to get the host_uuid
    for item in mapping:
        if 'entities' in item:
            for _item in item['entities']:
                if 'host_uuid' in _item:
                    system_uuid = _item['host_uuid']
                    break
    message = f"Host UUID {system_uuid} found for VM: {guest_uuid}"
    for line in logs.split('\n'):
        if message in line:
            return "Host UUID found for VM"
    else:
        raise VirtWhoError(f"Failed to get Host UUID {system_uuid} found for VM: {guest_uuid}")


def deploy_validation(hypervisor_type):
    """Checkout the deploy result
    :param str hypervisor_type: esx, libvirt, rhevm, xen, libvirt, kubevirt, ahv
    :raises: VirtWhoError: If failed to start virt-who service.
    :ruturn: hypervisor_name and guest_name
    """
    status = get_virtwho_status()
    if status != 'running':
        raise VirtWhoError("Failed to start virt-who service")
    hypervisor_name, guest_name = _get_hypervisor_mapping(hypervisor_type)
    for host in Host.list({'search': hypervisor_name}):
        Host.delete({'id': host['id']})
    restart_virtwho_service()
    return hypervisor_name, guest_name


def deploy_configure_by_command(command, hypervisor_type, debug=False, org='Default_Organization'):
    """Deploy and run virt-who service by the hammer command.

    :param str command: get the command by UI/CLI/API, it should be like:
        `hammer virt-who-config deploy --id 1 --organization-id 1`
    :param str hypervisor_type: esx, libvirt, rhevm, xen, libvirt, kubevirt, ahv
    :param bool debug: if VIRTWHO_DEBUG=1, this option should be True.
    :param str org: Organization Label
    """
    virtwho_cleanup()
    guest_name, guest_uuid = get_guest_info(hypervisor_type)
    if Host.list({'search': guest_name}):
        Host.delete({'name': guest_name})
    register_system(get_system(hypervisor_type), org=org)
    ret, stdout = runcmd(command)
    if ret != 0 or 'Finished successfully' not in stdout:
        raise VirtWhoError(f"Failed to deploy configure by {command}")
    if debug:
        return deploy_validation(hypervisor_type)
    return None


def deploy_configure_by_script(
    script_content, hypervisor_type, debug=False, org='Default_Organization'
):
    """Deploy and run virt-who service by the shell script.
    :param str script_content: get the script by UI or API.
    :param str hypervisor_type: esx, libvirt, rhevm, xen, libvirt, kubevirt, ahv
    :param bool debug: if VIRTWHO_DEBUG=1, this option should be True.
    :param str org: Organization Label
    """
    script_filename = "/tmp/deploy_script.sh"
    script_content = script_content.replace('&amp;', '&').replace('&gt;', '>').replace('&lt;', '<')
    virtwho_cleanup()
    register_system(get_system(hypervisor_type), org=org)
    with open(script_filename, 'w') as fp:
        fp.write(script_content)
    ssh.get_client().put(script_filename)
    ret, stdout = runcmd(f'sh {script_filename}')
    if ret != 0 or 'Finished successfully' not in stdout:
        raise VirtWhoError(f"Failed to deploy configure by {script_filename}")
    if debug:
        return deploy_validation(hypervisor_type)
    return None


def deploy_configure_by_command_check(command):
    """Deploy and run virt-who service by the hammer command to check deploy log.

    :param str command: get the command by UI/CLI/API, it should be like:
        `hammer virt-who-config deploy --id 1 --organization-id 1`
    :param str hypervisor_type: esx, libvirt, rhevm, xen, libvirt, kubevirt, ahv
    :param str org: Organization Label
    """
    virtwho_cleanup()
    try:
        ret, stdout = runcmd(command)
    except Exception as err:
        raise VirtWhoError(f"Failed to deploy configure by {command}") from err
    else:
        if ret != 0 or 'Finished successfully' not in stdout:
            raise VirtWhoError(f"Failed to deploy configure by {command}")
        return 'Finished successfully'


def restart_virtwho_service():
    """
    Do the following:
    1. remove rhsm.log to ensure there are no old messages.
    2. restart virt-who service via systemctl command
    """
    runcmd("rm -f /var/log/rhsm/rhsm.log")
    runcmd("systemctl restart virt-who; sleep 10")


def update_configure_option(option, value, config_file):
    """
    Update option in virt-who config file
    :param option: the option you want to update
    :param value:  set the option to the value
    :param config_file: path of virt-who config file
    """
    cmd = f'sed -i "s|^{option}.*|{option}={value}|g" {config_file}'
    ret, output = runcmd(cmd)
    if ret != 0:
        raise VirtWhoError(f"Failed to set option {option} value to {value}")


def delete_configure_option(option, config_file):
    """
    Delete option in virt-who config file
    :param option: the option you want to delete
    :param config_file: path of virt-who config file
    """
    cmd = f'sed -i "/^{option}/d" {config_file}; sed -i "/^#{option}/d" {config_file}'
    ret, output = runcmd(cmd)
    if ret != 0:
        raise VirtWhoError(f"Failed to delete option {option}")


def add_configure_option(option, value, config_file):
    """
    Add option to virt-who config file
    :param option: the option you want to add
    :param value:  the value of the option
    :param config_file: path of virt-who config file
    """
    try:
        get_configure_option(option, config_file)
    except Exception as err:
        cmd = f'echo -e "\n{option}={value}" >> {config_file}'
        ret, _ = runcmd(cmd)
        if ret != 0:
            raise VirtWhoError(f"Failed to add option {option}={value}") from err
    else:
        raise VirtWhoError(f"option {option} is already exist in {config_file}")


def hypervisor_json_create(hypervisors, guests):
    """
    Create a hypervisor guest json data. For example:
    {'hypervisors': [{'hypervisorId': '820b5143-3885-4dba-9358-4ce8c30d934e',
    'guestIds': [{'guestId': 'afb91b1f-8438-46f5-bc67-d7ab328ef782', 'state': 1,
    'attributes': {'active': 1, 'virtWhoType': 'esx'}}]}]}
    :param hypervisors: how many hypervisors will be created
    :param guests: how many guests will be created
    """
    hypervisors_list = []
    for _ in range(hypervisors):
        guest_list = []
        for _ in range(guests):
            guest_list.append(
                {
                    "guestId": str(uuid.uuid4()),
                    "state": 1,
                    "attributes": {"active": 1, "virtWhoType": "esx"},
                }
            )
        name = str(uuid.uuid4())
        hypervisor = {"guestIds": guest_list, "name": name, "hypervisorId": {"hypervisorId": name}}
        hypervisors_list.append(hypervisor)
    return {"hypervisors": hypervisors_list}


def hypervisor_fake_json_create(hypervisors, guests):
    """
    Create a hypervisor guest json data for fake config usages. For example:
    {'hypervisors': [{'uuid': '820b5143-3885-4dba-9358-4ce8c30d934e',
    'guests': [{'guestId': 'afb91b1f-8438-46f5-bc67-d7ab328ef782', 'state': 1,
    'attributes': {'active': 1, 'virtWhoType': 'esx'}}]}]}
    :param hypervisors: how many hypervisors will be created
    :param guests: how many guests will be created
    """
    hypervisors_list = [
        {
            'guests': [
                {
                    "guestId": str(uuid.uuid4()),
                    "state": 1,
                    "attributes": {"active": 1, "virtWhoType": "esx"},
                }
                for _ in range(guests)
            ],
            'name': str(uuid.uuid4()),
            'uuid': str(uuid.uuid4()),
        }
        for _ in range(hypervisors)
    ]
    return {"hypervisors": hypervisors_list}


def create_fake_hypervisor_content(org_label, hypervisors, guests):
    """
    Post the fake hypervisor content to satellite server
    :param hypervisors: how many hypervisors will be created
    :param guests: how many guests will be created
    :param org_label: the label of the Organization
    :return data: the hypervisor content
    """
    data = hypervisor_json_create(hypervisors, guests)
    url = f"https://{settings.server.hostname}/rhsm/hypervisors/{org_label}"
    auth = (settings.server.admin_username, settings.server.admin_password)
    result = requests.post(url, auth=auth, verify=False, json=data)
    assert result.status_code == 200
    return data


def get_hypervisor_info(hypervisor_type):
    """
    Get the hypervisor_name and guest_name from rhsm.log.
    """
    hypervisor_name, guest_name = _get_hypervisor_mapping(hypervisor_type)
    return hypervisor_name, guest_name


def virtwho_package_locked():
    """
    Uninstall virt-who package and lock the satellite-maintain packages.
    """
    runcmd('rpm -e virt-who; satellite-maintain packages lock')
    result = runcmd('satellite-maintain packages is-locked')
    assert "Packages are locked" in result[1]


def create_http_proxy(org, location, name=None, url=None, http_type='https'):
    """
    Creat a new http-proxy with attributes.
    :param name: Name of the proxy
    :param url: URL of the proxy including schema (https://proxy.example.com:8080)
    :param http_type: https or http
    :param org: instance of the organization
    :return:
    """
    org = entities.Organization().search(query={'search': f'name="{org.name}"'})[0]
    http_proxy_name = name or gen_string('alpha', 15)
    http_proxy_url = (
        url or f'{gen_url(scheme=http_type)}:{gen_integer(min_value=10, max_value=9999)}'
    )
    http_proxy = entities.HTTPProxy(
        name=http_proxy_name,
        url=http_proxy_url,
        organization=[org.id],
        location=[location.id],
    ).create()
    return http_proxy.url, http_proxy.name, http_proxy.id


def get_configure_command_option(deploy_type, args, org=DEFAULT_ORG):
    """Return the deploy command line based on option.
    :param str option: the unique id of the configure file you have created.
    :param str org: the satellite organization name.
    """
    username, password = Base._get_username_password()
    if deploy_type == 'location-id':
        return f"hammer -u {username} -p {password} virt-who-config deploy --id {args['id']} --location-id '{args['location-id']}' "
    if deploy_type == 'organization-title':
        return f"hammer -u {username} -p {password} virt-who-config deploy --id {args['id']} --organization-title '{args['organization-title']}' "
    if deploy_type == 'name':
        return f"hammer -u {username} -p {password} virt-who-config deploy --name {args['name']} --organization '{org}' "
    return None


def vw_fake_conf_create(
    owner,
    rhsm_hostname,
    rhsm_username,
    rhsm_encrypted_password,
    fake_conf_file,
    json_file,
    is_hypervisor=True,
):
    """Create fake config file
    :param owner: Name of the Owner
    :param rhsm_hostname: Name of the rhsm_hostname
    :param rhsm_username: Name of the rhsm_username
    :param rhsm_encrypted_password: Value of the rhsm_encrypted_password
    :param fake_conf_file: Name of the fake_conf_file
    :param json_file: Name of the json_file
    :param is_hypervisor: Default ir True
    :return:
    """
    conf_name = fake_conf_file.split("/")[-1].split(".")[0]
    file = f'{fake_conf_file}\n'
    title = f'[{conf_name}]\n'
    type = 'type=fake\n'
    json = f'file={json_file}\n'
    is_hypervisor = f'is_hypervisor={is_hypervisor}\n'
    owner = f'owner={owner}\n'
    env = 'env = Library\n'
    rhsm_hostname = f'rhsm_hostname={rhsm_hostname}\n'
    rhsm_username = f'rhsm_username={rhsm_username}\n'
    rhsm_encrypted_password = f'rhsm_encrypted_password={rhsm_encrypted_password}\n'
    rhsm_prefix = 'rhsm_prefix=/rhsm\n'
    rhsm_port = 'rhsm_port=443\n'
    cmd = f'cat <<EOF > {file}{title}{type}{json}{is_hypervisor}{owner}{env}{rhsm_hostname}{rhsm_username}{rhsm_encrypted_password}{rhsm_prefix}{rhsm_port}EOF'
    runcmd(cmd)


def vw_run_option(option):
    """virt who run by option
    :param option:  -d, --debug  -o, --one-shot  -i INTERVAL, --interval INTERVAL -p, --print -c CONFIGS, --config CONFIGS --version
    :ruturn:
    """
    runcmd('systemctl stop virt-who')
    runcmd('pkill -9 virt-who')
    runcmd(f'virt-who -{option}')


def hypervisor_guest_mapping_check_legacy_ui(
    org_session, form_data_ui, default_location, hypervisor_name, guest_name
):
    # Check virt-who config status
    assert org_session.virtwho_configure.search(form_data_ui['name'])[0]['Status'] == 'ok'
    # Check Hypervisor host subscription status and hypervisor host and virtual guest mapping in Legacy UI
    org_session.location.select(default_location.name)
    hypervisor_display_name = org_session.contenthost.search(hypervisor_name)[0]['Name']
    hypervisorhost = org_session.contenthost.read_legacy_ui(hypervisor_display_name)
    assert hypervisorhost['details']['virtual_guest'] == '1 Content Host'
    # Check virtual guest subscription status and hypervisor host and virtual guest mapping in Legacy UI
    virtualguest = org_session.contenthost.read_legacy_ui(guest_name)
    assert virtualguest['details']['virtual_host'] == hypervisor_display_name


def hypervisor_guest_mapping_newcontent_ui(org_session, hypervisor_name, guest_name):
    hypervisor_display_name = org_session.contenthost.search(hypervisor_name)[0]['Name']
    hypervisorhost_new_overview = org_session.host_new.get_details(
        hypervisor_display_name, 'overview'
    )
    assert hypervisorhost_new_overview['overview']['host_status']['status_success'] == '1'
    # hypervisor host Check details
    hypervisorhost_new_detais = org_session.host_new.get_details(hypervisor_display_name, 'details')
    assert (
        hypervisorhost_new_detais['details']['system_properties']['sys_properties']['virtual_host']
        == hypervisor_display_name
    )
    assert (
        hypervisorhost_new_detais['details']['system_properties']['sys_properties']['name']
        == guest_name
    )
    # Check guest overview
    guest_new_overview = org_session.host_new.get_details(guest_name, 'overview')
    assert guest_new_overview['overview']['host_status']['status_success'] == '1'
    # Check guest details
    virtualguest_new_detais = org_session.host_new.get_details(guest_name, 'details')
    assert (
        virtualguest_new_detais['details']['system_properties']['sys_properties']['virtual_host']
        == hypervisor_display_name
    )
    assert (
        virtualguest_new_detais['details']['system_properties']['sys_properties']['name']
        == guest_name
    )
