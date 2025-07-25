"""Test class for Hosts UI

:Requirement: Host

:CaseAutomation: Automated

:CaseComponent: Hosts

:Team: Phoenix-subscriptions

:CaseImportance: High

"""

import copy
import csv
from datetime import UTC, datetime, timedelta
import json
import os
import re
import time

from airgun.exceptions import DisabledWidgetError, NoSuchElementException
from box import Box
import pytest
from wait_for import wait_for
import yaml

from robottelo.config import settings
from robottelo.constants import (
    ANY_CONTEXT,
    DEFAULT_ARCHITECTURE,
    DEFAULT_CV,
    DEFAULT_LOC,
    DUMMY_BOOTC_FACTS,
    ENVIRONMENT,
    FAKE_1_CUSTOM_PACKAGE,
    FAKE_7_CUSTOM_PACKAGE,
    FAKE_8_CUSTOM_PACKAGE,
    FAKE_8_CUSTOM_PACKAGE_NAME,
    FOREMAN_PROVIDERS,
    OSCAP_PERIOD,
    OSCAP_WEEKDAY,
    REPO_TYPE,
    REPOS,
    ROLES,
)
from robottelo.constants.repos import CUSTOM_FILE_REPO
from robottelo.exceptions import APIResponseError
from robottelo.utils.datafactory import gen_string
from tests.foreman.api.test_errata import cv_publish_promote


def _get_set_from_list_of_dict(value):
    """Returns a set of tuples representation of each dict sorted by keys

    :param list value: a list of simple dict.
    """
    return {tuple(sorted(list(global_param.items()), key=lambda t: t[0])) for global_param in value}


# this fixture inherits the fixture called ui_user in confest.py, method name has to be same
@pytest.fixture(scope='module')
def ui_user(ui_user, smart_proxy_location, module_target_sat):
    module_target_sat.api.User(
        id=ui_user.id,
        default_location=smart_proxy_location,
    ).update(['default_location'])
    return ui_user


@pytest.fixture
def ui_admin_user(target_sat):
    """Admin user."""
    admin_user = target_sat.api.User().search(
        query={'search': f'login={settings.server.admin_username}'}
    )[0]
    admin_user.password = settings.server.admin_password

    return admin_user


@pytest.fixture
def ui_view_hosts_user(target_sat, current_sat_org, current_sat_location):
    """User with View hosts role."""
    role = target_sat.api.Role().search(query={'search': 'name="View hosts"'})[0]
    password = gen_string('alphanumeric')
    user = target_sat.api.User(
        admin=False,
        location=[current_sat_location],
        organization=[current_sat_org],
        role=[role],
        password=password,
    ).create()
    user.password = password

    yield user

    user.delete()


@pytest.fixture(params=['ui_admin_user', 'ui_view_hosts_user'])
def ui_hosts_columns_user(request):
    """Parametrized fixture returning defined users for the UI session."""
    return request.getfixturevalue(request.param)


@pytest.fixture
def scap_policy(scap_content, target_sat):
    return target_sat.cli_factory.make_scap_policy(
        {
            'name': gen_string('alpha'),
            'deploy-by': 'ansible',
            'scap-content-id': scap_content["scap_id"],
            'scap-content-profile-id': scap_content["scap_profile_id"],
            'period': OSCAP_PERIOD['weekly'].lower(),
            'weekday': OSCAP_WEEKDAY['friday'].lower(),
        }
    )


second_scap_policy = scap_policy


@pytest.fixture(scope='module')
def module_global_params(module_target_sat):
    """Create 3 global parameters and clean up at teardown"""
    global_parameters = []
    for _ in range(3):
        global_parameter = module_target_sat.api.CommonParameter(
            name=gen_string('alpha'), value=gen_string('alphanumeric')
        ).create()
        global_parameters.append(global_parameter)
    yield global_parameters
    # cleanup global parameters
    for global_parameter in global_parameters:
        global_parameter.delete()


@pytest.fixture
def tracer_install_host(rex_contenthost, target_sat):
    """This fixture automatically configures IPv6 support based on the host's network type and creates
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
    return rex_contenthost


@pytest.fixture
def new_host_ui(target_sat):
    """Changes the setting to use the New All Host UI
    then returns it back to the normal value"""
    all_hosts_setting = target_sat.api.Setting().search(
        query={'search': f'name={"new_hosts_page"}'}
    )[0]
    all_hosts_setting.value = 'True'
    all_hosts_setting.update({'value'})
    yield
    all_hosts_setting.value = 'False'
    all_hosts_setting.update({'value'})


@pytest.mark.e2e
def test_positive_end_to_end(session, module_global_params, target_sat, host_ui_options):
    """Create a new Host with parameters, config group. Check host presence on
        the dashboard. Update name with 'new' prefix and delete.

    :id: d2f86309-1a6d-42dc-a865-9e607cd25ae5

    :expectedresults: Host is created with parameters, config group. Updated
        and deleted.

    :BZ: 1419161
    """
    api_values, host_name = host_ui_options
    global_params = [
        global_param.to_json_dict(lambda attr, field: attr in ['name', 'value'])
        for global_param in module_global_params
    ]
    host_parameters = []
    for _ in range(2):
        host_parameters.append(dict(name=gen_string('alpha'), value=gen_string('alphanumeric')))
    expected_host_parameters = copy.deepcopy(host_parameters)
    # override the first global parameter
    overridden_global_parameter = {'name': global_params[0]['name'], 'value': gen_string('alpha')}
    expected_host_parameters.append(overridden_global_parameter)
    expected_global_parameters = copy.deepcopy(global_params)
    for global_param in expected_global_parameters:
        # update with overridden expected value
        if global_param['name'] == overridden_global_parameter['name']:
            global_param['overridden'] = True
        else:
            global_param['overridden'] = False
    new_name = f"new{gen_string('alpha').lower()}"
    new_host_name = f"{new_name}.{api_values['interfaces.interface.domain']}"
    with session:
        api_values.update(
            {
                'parameters.host_params': host_parameters,
                'parameters.global_params': [overridden_global_parameter],
            }
        )
        session.host.create(api_values)
        assert session.host.search(host_name)[0]['Name'] == host_name
        values = session.host.read(host_name, widget_names=['parameters'])
        assert _get_set_from_list_of_dict(
            values['parameters']['host_params']
        ) == _get_set_from_list_of_dict(expected_host_parameters)
        assert _get_set_from_list_of_dict(expected_global_parameters).issubset(
            _get_set_from_list_of_dict(values['parameters']['global_params'])
        )

        # check host presence on the dashboard
        dashboard_values = session.dashboard.read('NewHosts')['hosts']
        displayed_host = [row for row in dashboard_values if row['Host'] == host_name][0]
        assert api_values['operating_system.operating_system'] in displayed_host['Operating System']
        assert displayed_host['Installed'] == 'N/A'
        # update
        session.host.update(host_name, {'host.name': new_name})
        assert not session.host.search(host_name)
        assert session.host.search(new_host_name)[0]['Name'] == new_host_name
        # delete
        session.host.delete(new_host_name)
        assert not target_sat.api.Host().search(query={'search': f'name="{new_host_name}"'})


def test_positive_read_from_details_page(session, module_host_template):
    """Create new Host and read all its content through details page

    :id: ffba5d40-918c-440e-afbb-6b910db3a8fb

    :expectedresults: Host is created and has expected content
    """

    template = module_host_template
    template.name = gen_string('alpha').lower()
    host = template.create()
    os_name = f'{template.operatingsystem.name} {template.operatingsystem.major}'
    host_name = host.name
    with session:
        assert session.host.search(host_name)[0]['Name'] == host_name
        values = session.host.get_details(host_name)
        assert values['properties']['properties_table']['Status'] == 'OK'
        assert 'Pending installation' in values['properties']['properties_table']['Build']
        assert values['properties']['properties_table']['Domain'] == template.domain.name
        assert values['properties']['properties_table']['MAC Address'] == host.mac
        assert (
            values['properties']['properties_table']['Architecture'] == template.architecture.name
        )
        assert values['properties']['properties_table']['Operating System'] == os_name
        assert values['properties']['properties_table']['Location'] == template.location.name
        assert (
            values['properties']['properties_table']['Organization'] == template.organization.name
        )
        assert 'Admin User' in values['properties']['properties_table']['Owner']


def test_read_host_with_ics_domain(
    session, module_host_template, module_location, module_org, module_target_sat
):
    """Create new Host with ics domain name and verify that it can be read

    :id: 54e3db92-16c2-412b-bf68-44d479c5987b

    :steps:
        1. Create a host with a domain ending in .ics
        2. Read the host's details through the UI

    :expectedresults: Host ending with ics domain name can be accessed through Host UI

    :customerscenario: true

    :Verifies: SAT-26202
    """
    template = module_host_template
    template.name = gen_string('alpha').lower()
    ics_domain = module_target_sat.api.Domain(
        location=[module_location],
        organization=[module_org],
        name=gen_string('alpha').lower() + '.ics',
    ).create()
    template.domain = ics_domain
    host = template.create()
    host_name = host.name
    with module_target_sat.ui_session() as session:
        values = session.host_new.get_details(host_name, widget_names='details')
        assert (
            values['details']['system_properties']['sys_properties']['domain']
            == template.domain.name
        )
        assert values['details']['system_properties']['sys_properties']['name'] == host_name


def test_positive_read_from_edit_page(session, host_ui_options):
    """Create new Host and read all its content through edit page

    :id: 758fcab3-b363-4bfc-8f5d-173098a7e72d

    :expectedresults: Host is created and has expected content
    """
    api_values, host_name = host_ui_options
    with session:
        session.location.select(api_values['host.location'])
        session.host.create(api_values)
        assert session.host.search(host_name)[0]['Name'] == host_name
        values = session.host.read(host_name)
        assert values['host']['name'] == host_name.partition('.')[0]
        assert values['host']['organization'] == api_values['host.organization']
        assert (
            values['operating_system']['architecture']
            == api_values['operating_system.architecture']
        )
        assert (
            values['operating_system']['operating_system']
            == api_values['operating_system.operating_system']
        )
        assert values['operating_system']['media_type'] == 'All Media'
        assert values['operating_system']['media'] == api_values['operating_system.media']
        assert values['operating_system']['ptable'] == api_values['operating_system.ptable']
        assert (
            values['interfaces']['interfaces_list'][0]['Identifier']
            == api_values['interfaces.interface.device_identifier']
        )
        assert values['interfaces']['interfaces_list'][0]['Type'] == 'Interface physical'
        assert (
            values['interfaces']['interfaces_list'][0]['MAC Address']
            == api_values['interfaces.interface.mac']
        )
        assert values['interfaces']['interfaces_list'][0]['FQDN'] == host_name
        assert session._user in values['additional_information']['owned_by']
        assert values['additional_information']['enabled'] is True


def test_positive_assign_taxonomies(
    session, module_org, smart_proxy_location, target_sat, function_org, function_location_with_org
):
    """Ensure Host organization and Location can be assigned.

    :id: 52466df5-6f56-4faa-b0f8-42b63731f494

    :expectedresults: Host Assign Organization and Location actions are
        working as expected.
    """
    host = target_sat.api.Host(organization=module_org, location=smart_proxy_location).create()
    with session:
        assert session.host.search(host.name)[0]['Name'] == host.name
        session.host.apply_action(
            'Assign Organization',
            [host.name],
            {'organization': function_org.name, 'on_mismatch': 'Fix Organization on Mismatch'},
        )
        assert not target_sat.api.Host(organization=module_org).search(
            query={'search': f'name="{host.name}"'}
        )
        assert (
            len(
                target_sat.api.Host(organization=function_org).search(
                    query={'search': f'name="{host.name}"'}
                )
            )
            == 1
        )
        session.organization.select(org_name=function_org.name)
        assert session.host.search(host.name)[0]['Name'] == host.name
        session.host.apply_action(
            'Assign Location',
            [host.name],
            {
                'location': function_location_with_org.name,
                'on_mismatch': 'Fix Location on Mismatch',
            },
        )
        assert not target_sat.api.Host(location=smart_proxy_location).search(
            query={'search': f'name="{host.name}"'}
        )
        assert (
            len(
                target_sat.api.Host(location=function_location_with_org).search(
                    query={'search': f'name="{host.name}"'}
                )
            )
            == 1
        )
        session.location.select(loc_name=function_location_with_org.name)
        assert session.host.search(host.name)[0]['Name'] == host.name
        values = session.host.get_details(host.name)
        assert values['properties']['properties_table']['Organization'] == function_org.name
        assert (
            values['properties']['properties_table']['Location'] == function_location_with_org.name
        )


@pytest.mark.skip_if_not_set('oscap')
def test_positive_assign_compliance_policy(
    session, scap_policy, second_scap_policy, target_sat, function_host
):
    """Ensure host compliance Policy can be assigned.

    :id: 323661a4-e849-4cc2-aa39-4b4a5fe2abed

    :expectedresults: Host Assign/Unassign Compliance Policy action is working as
        expected.

    :BZ: 1862135
    """
    org = function_host.organization.read()
    loc = function_host.location.read()
    # add host organization and location to scap policy
    content = target_sat.api.ScapContents(id=scap_policy['scap-content-id']).read()
    content.organization.append(org)
    content.location.append(loc)
    target_sat.api.ScapContents(
        id=scap_policy['scap-content-id'],
        organization=content.organization,
        location=content.location,
    ).update(['organization', 'location'])
    for sp in [scap_policy, second_scap_policy]:
        target_sat.api.CompliancePolicies(
            id=sp['id'],
            organization=content.organization,
            location=content.location,
        ).update(['organization', 'location'])

    with session:
        session.organization.select(org_name=org.name)
        session.location.select(loc_name=loc.name)
        assert not session.host.search(f'compliance_policy = {scap_policy["name"]}')
        assert session.host.search(function_host.name)[0]['Name'] == function_host.name
        session.host.apply_action(
            'Assign Compliance Policy', [function_host.name], {'policy': scap_policy['name']}
        )
        session.host.apply_action(
            'Assign Compliance Policy', [function_host.name], {'policy': second_scap_policy['name']}
        )
        assert (
            session.host.search(f'compliance_policy = {scap_policy["name"]}')[0]['Name']
            == function_host.name
        )
        session.host.apply_action(
            'Assign Compliance Policy', [function_host.name], {'policy': scap_policy['name']}
        )
        assert (
            session.host.search(f'compliance_policy = {scap_policy["name"]}')[0]['Name']
            == function_host.name
        )
        session.host.apply_action(
            'Unassign Compliance Policy', [function_host.name], {'policy': scap_policy['name']}
        )
        assert not session.host.search(f'compliance_policy = {scap_policy["name"]}')
        assert (
            session.host.search(f'compliance_policy = {second_scap_policy["name"]}')[0]['Name']
            == function_host.name
        )


@pytest.mark.skipif((settings.ui.webdriver != 'chrome'), reason='Only tested on Chrome')
def test_positive_export(session, target_sat, function_org, function_location):
    """Create few hosts and export them via UI

    :id: ffc512ad-982e-4b60-970a-41e940ebc74c

    :expectedresults: csv file contains same values as on web UI
    """
    hosts = [
        target_sat.api.Host(organization=function_org, location=function_location).create()
        for _ in range(3)
    ]
    expected_fields = {(host.name, host.operatingsystem.read().title) for host in hosts}
    with session:
        session.organization.select(function_org.name)
        session.location.select(function_location.name)
        file_path = session.host.export()
        assert os.path.isfile(file_path)
        with open(file_path, newline='') as csvfile:
            actual_fields = []
            for row in csv.DictReader(csvfile):
                actual_fields.append((row['Name'], row['Operatingsystem']))
        assert set(actual_fields) == expected_fields


@pytest.mark.skipif(
    (settings.ui.webdriver != 'chrome'), reason='Currently only chrome is supported'
)
def test_positive_export_selected_columns(target_sat, current_sat_location):
    """Select certain columns in the hosts table and check that they are exported in the CSV file.

    :id: 2b65c1d6-0b94-11ef-a4b7-000c2989e153

    :steps:
        1. Select different columns to be displayed in the hosts table.
        2. Export the hosts into CSV file.

    :expectedresults: All columns selected in the UI table should be exported in the CSV file.

    :BZ: 2167146

    :customerscenario: true
    """
    columns = (
        Box(ui='Power', csv='Power Status', displayed=True),
        Box(ui='Recommendations', csv='Insights Recommendations Count', displayed=True),
        Box(ui='Name', csv='Name', displayed=True),
        Box(ui='IPv4', csv='Ip', displayed=True),
        Box(ui='IPv6', csv='Ip6', displayed=True),
        Box(ui='MAC', csv='Mac', displayed=True),
        Box(ui='OS', csv='Operatingsystem', displayed=True),
        Box(ui='Owner', csv='Owner', displayed=True),
        Box(ui='Host group', csv='Hostgroup', displayed=True),
        Box(ui='Boot time', csv='Reported Data - Boot Time', displayed=True),
        Box(ui='Last report', csv='Last Report', displayed=True),
        Box(ui='Comment', csv='Comment', displayed=True),
        Box(ui='Model', csv='Compute Resource Or Model', displayed=True),
        Box(ui='Sockets', csv='Reported Data - Sockets', displayed=True),
        Box(ui='Cores', csv='Reported Data - Cores', displayed=True),
        Box(ui='RAM', csv='Reported Data - Ram', displayed=True),
        Box(ui='Virtual', csv='Virtual', displayed=True),
        Box(ui='Disks space', csv='Reported Data - Disks Total', displayed=True),
        Box(ui='Kernel version', csv='Reported Data - Kernel Version', displayed=True),
        Box(ui='BIOS vendor', csv='Reported Data - Bios Vendor', displayed=True),
        Box(ui='BIOS release date', csv='Reported Data - Bios Release Date', displayed=True),
        Box(ui='BIOS version', csv='Reported Data - Bios Version', displayed=True),
        Box(ui='RHEL Lifecycle status', csv='Rhel Lifecycle Status', displayed=True),
        Box(ui='Installable updates', csv='Installable ...', displayed=False),
        Box(ui='Lifecycle environment', csv='Lifecycle Environment', displayed=True),
        Box(ui='Content view', csv='Content View', displayed=True),
        Box(ui='Registered', csv='Registered', displayed=True),
        Box(ui='Last checkin', csv='Last Checkin', displayed=True),
    )

    with target_sat.ui_session() as session:
        session.location.select(loc_name=current_sat_location.name)
        session.host.manage_table_columns({column.ui: column.displayed for column in columns})
        file_path = session.host.export()
        with open(file_path, newline='') as fh:
            csvfile = csv.DictReader(fh)
            assert set(csvfile.fieldnames) == set(
                [column.csv for column in columns if column.displayed]
            )


def test_positive_create_with_inherited_params(
    session, target_sat, function_org, function_location_with_org
):
    """Create a new Host in organization and location with parameters

    :BZ: 1287223

    :id: 628122f2-bda9-4aa1-8833-55debbd99072

    :expectedresults: Host has inherited parameters from organization and
        location

    :CaseImportance: High
    """
    org_param = dict(name=gen_string('alphanumeric'), value=gen_string('alphanumeric'))
    loc_param = dict(name=gen_string('alphanumeric'), value=gen_string('alphanumeric'))
    host_template = target_sat.api.Host(
        organization=function_org, location=function_location_with_org
    )
    host_template.create_missing()
    host = host_template.create()
    host_name = host.name
    with session:
        session.organization.update(function_org.name, {'parameters.resources': org_param})
        session.location.update(
            function_location_with_org.name, {'parameters.resources': loc_param}
        )
        session.organization.select(org_name=function_org.name)
        session.location.select(loc_name=function_location_with_org.name)
        values = session.host.read(host_name, 'parameters')
        expected_params = {
            (org_param['name'], org_param['value']),
            (loc_param['name'], loc_param['value']),
        }
        assert expected_params.issubset(
            {(param['name'], param['value']) for param in values['parameters']['global_params']}
        )


def test_negative_delete_primary_interface(session, host_ui_options):
    """Attempt to delete primary interface of a host

    :id: bc747e2c-38d9-4920-b4ae-6010851f704e

    :customerscenario: true

    :BZ: 1417119

    :expectedresults: Interface was not deleted
    """
    values, host_name = host_ui_options
    interface_id = values['interfaces.interface.device_identifier']
    with session:
        session.location.select(values['host.location'])
        session.host.create(values)
        with pytest.raises(DisabledWidgetError) as context:
            session.host.delete_interface(host_name, interface_id)
        assert 'Interface Delete button is disabled' in str(context.value)


def test_positive_view_hosts_with_non_admin_user(
    test_name, module_org, smart_proxy_location, target_sat
):
    """View hosts and content hosts as a non-admin user with only view_hosts, edit_hosts
    and view_organization permissions

    :BZ: 1642076, 1801630

    :customerscenario: true

    :id: 19a07026-0550-11ea-bfdc-98fa9b6ecd5a

    :expectedresults: user with only view_hosts, edit_hosts and view_organization permissions
        is able to read content hosts and hosts
    """
    user_password = gen_string('alpha')
    role = target_sat.api.Role(organization=[module_org]).create()
    target_sat.api_factory.create_role_permissions(
        role, {'Organization': ['view_organizations'], 'Host': ['view_hosts']}
    )
    user = target_sat.api.User(
        role=[role],
        admin=False,
        password=user_password,
        organization=[module_org],
        location=[smart_proxy_location],
        default_organization=module_org,
        default_location=smart_proxy_location,
    ).create()
    created_host = target_sat.api.Host(
        location=smart_proxy_location, organization=module_org
    ).create()
    with target_sat.ui_session(test_name, user=user.login, password=user_password) as session:
        host = session.host.get_details(created_host.name, widget_names='breadcrumb')
        assert host['breadcrumb'] == created_host.name
        content_host = session.contenthost.read(created_host.name, widget_names='breadcrumb')
        assert content_host['breadcrumb'] == created_host.name


def test_positive_remove_parameter_non_admin_user(
    test_name, module_org, smart_proxy_location, target_sat, expected_permissions
):
    """Remove a host parameter as a non-admin user with enough permissions

    :BZ: 1996035

    :id: 598111c1-fdb6-42e9-8c28-fae999b5d112

    :expectedresults: user with sufficient permissions may remove host
        parameter
    """
    user_password = gen_string('alpha')
    parameter = {'name': gen_string('alpha'), 'value': gen_string('alpha')}
    role = target_sat.api.Role(organization=[module_org]).create()
    target_sat.api_factory.create_role_permissions(
        role,
        {
            'Parameter': expected_permissions['Parameter'],
            'Host': expected_permissions['Host'],
            'Operatingsystem': ['view_operatingsystems'],
        },
    )
    user = target_sat.api.User(
        role=[role],
        admin=False,
        password=user_password,
        organization=[module_org],
        location=[smart_proxy_location],
        default_organization=module_org,
        default_location=smart_proxy_location,
    ).create()
    host = target_sat.api.Host(
        content_facet_attributes={
            'content_view_id': module_org.default_content_view.id,
            'lifecycle_environment_id': module_org.library.id,
        },
        location=smart_proxy_location,
        organization=module_org,
        host_parameters_attributes=[parameter],
    ).create()
    with target_sat.ui_session(test_name, user=user.login, password=user_password) as session:
        values = session.host.read(host.name, 'parameters')
        assert values['parameters']['host_params'][0] == parameter
        session.host.update(host.name, {'parameters.host_params': []})
        values = session.host.read(host.name, 'parameters')
        assert not values['parameters']['host_params']


def test_negative_remove_parameter_non_admin_user(
    test_name, module_org, smart_proxy_location, target_sat, expected_permissions
):
    """Attempt to remove host parameter as a non-admin user with
    insufficient permissions

    :BZ: 1317868

    :id: 78fd230e-2ec4-4158-823b-ddbadd5e232f

    :customerscenario: true

    :expectedresults: user with insufficient permissions is unable to
        remove host parameter, 'Remove' link is not visible for him
    """

    user_password = gen_string('alpha')
    parameter = {'name': gen_string('alpha'), 'value': gen_string('alpha')}
    role = target_sat.api.Role(organization=[module_org]).create()
    target_sat.api_factory.create_role_permissions(
        role,
        {
            'Parameter': ['view_params'],
            'Host': expected_permissions['Host'],
            'Operatingsystem': ['view_operatingsystems'],
        },
    )
    user = target_sat.api.User(
        role=[role],
        admin=False,
        password=user_password,
        organization=[module_org],
        location=[smart_proxy_location],
        default_organization=module_org,
        default_location=smart_proxy_location,
    ).create()
    host = target_sat.api.Host(
        content_facet_attributes={
            'content_view_id': module_org.default_content_view.id,
            'lifecycle_environment_id': module_org.library.id,
        },
        location=smart_proxy_location,
        organization=module_org,
        host_parameters_attributes=[parameter],
    ).create()
    with target_sat.ui_session(test_name, user=user.login, password=user_password) as session:
        values = session.host.read(host.name, 'parameters')
        assert values['parameters']['host_params'][0] == parameter
        with pytest.raises(NoSuchElementException) as context:
            session.host.update(host.name, {'parameters.host_params': []})
        assert 'Remove Parameter' in str(context.value)


def test_positive_check_permissions_affect_create_procedure(
    test_name, smart_proxy_location, target_sat, function_org, function_role, expected_permissions
):
    """Verify whether user permissions affect what entities can be selected
    when host is created

    :id: 4502f99d-86fb-4655-a9dc-b2612cf849c6

    :customerscenario: true

    :expectedresults: user with specific permissions can choose only
        entities for create host procedure that he has access to

    :BZ: 1293716
    """
    # Create two lifecycle environments
    lc_env = target_sat.api.LifecycleEnvironment(organization=function_org).create()
    filter_lc_env = target_sat.api.LifecycleEnvironment(organization=function_org).create()
    # Create two content views and promote them to one lifecycle
    # environment which will be used in filter
    cv = target_sat.api.ContentView(organization=function_org).create()
    filter_cv = target_sat.api.ContentView(organization=function_org).create()
    for content_view in [cv, filter_cv]:
        content_view.publish()
        content_view = content_view.read()
        content_view.version[0].promote(data={'environment_ids': filter_lc_env.id})
    # Create two host groups
    hg = target_sat.api.HostGroup(organization=[function_org]).create()
    filter_hg = target_sat.api.HostGroup(organization=[function_org]).create()
    # Create lifecycle environment permissions and select one specific
    # environment user will have access to
    target_sat.api_factory.create_role_permissions(
        function_role,
        {
            'Katello::KTEnvironment': [
                'promote_or_remove_content_views_to_environments',
                'view_lifecycle_environments',
            ]
        },
        # allow access only to the mentioned here environment
        search=f'name = {filter_lc_env.name}',
    )
    # Add necessary permissions for content view as we did for lce
    target_sat.api_factory.create_role_permissions(
        function_role,
        {
            'Katello::ContentView': [
                'promote_or_remove_content_views',
                'view_content_views',
                'publish_content_views',
            ]
        },
        # allow access only to the mentioned here cv
        search=f'name = {filter_cv.name}',
    )
    # Add necessary permissions for hosts as we did for lce
    target_sat.api_factory.create_role_permissions(
        function_role,
        {'Host': ['create_hosts', 'view_hosts']},
        # allow access only to the mentioned here host group
        search=f'hostgroup_fullname = {filter_hg.name}',
    )
    # Add necessary permissions for host groups as we did for lce
    target_sat.api_factory.create_role_permissions(
        function_role,
        {'Hostgroup': ['view_hostgroups']},
        # allow access only to the mentioned here host group
        search=f'name = {filter_hg.name}',
    )
    # Add permissions for Organization and Location
    target_sat.api_factory.create_role_permissions(
        function_role,
        {
            'Organization': expected_permissions['Organization'],
            'Location': expected_permissions['Location'],
        },
    )
    # Create new user with a configured role
    user_password = gen_string('alpha')
    user = target_sat.api.User(
        role=[function_role],
        admin=False,
        password=user_password,
        organization=[function_org],
        location=[smart_proxy_location],
        default_organization=function_org,
        default_location=smart_proxy_location,
    ).create()
    host_fields = [
        {'name': 'host.hostgroup', 'unexpected_value': hg.name, 'expected_value': filter_hg.name},
        {
            'name': 'host.lce',
            'unexpected_value': lc_env.name,
            'expected_value': filter_lc_env.name,
        },
        {
            'name': 'host.content_view',
            'unexpected_value': cv.name,
            'expected_value': filter_cv.name,
            # content view selection needs the right lce to be selected
            'other_fields_values': {'host.lce': filter_lc_env.name},
        },
    ]
    with target_sat.ui_session(test_name, user=user.login, password=user_password) as session:
        for host_field in host_fields:
            values = {host_field['name']: host_field['unexpected_value']}
            values.update(host_field.get('other_fields_values', {}))
            with pytest.raises(NoSuchElementException) as context:
                session.host.helper.read_create_view(values)
            error_message = str(context.value)
            assert host_field['unexpected_value'] in error_message
            # After the NoSuchElementException from FilteredDropdown, airgun is not able to
            # navigate to other locations, Note in normal situation we should send Escape key to
            # browser.
            session.browser.refresh()
            values = {host_field['name']: host_field['expected_value']}
            values.update(host_field.get('other_fields_values', {}))
            create_values = session.host.helper.read_create_view(values, host_field['name'])
            tab_name, field_name = host_field['name'].split('.')
            assert create_values[tab_name][field_name] == host_field['expected_value']


def test_positive_search_by_parameter(session, module_org, smart_proxy_location, target_sat):
    """Search for the host by global parameter assigned to it

    :id: 8e61127c-d0a0-4a46-a3c6-22d3b2c5457c

    :expectedresults: Only one specific host is returned by search

    :BZ: 1725686
    """
    param_name = gen_string('alpha')
    param_value = gen_string('alpha')
    parameters = [{'name': param_name, 'value': param_value}]
    param_host = target_sat.api.Host(
        organization=module_org,
        location=smart_proxy_location,
        host_parameters_attributes=parameters,
    ).create()
    additional_host = target_sat.api.Host(
        organization=module_org, location=smart_proxy_location
    ).create()
    with session:
        # Check that hosts present in the system
        for host in [param_host, additional_host]:
            assert session.host.search(host.name)[0]['Name'] == host.name
        # Check that search by parameter returns only one host in the list
        values = session.host.search(f'params.{param_name} = {param_value}')
        assert len(values) == 1
        assert values[0]['Name'] == param_host.name


@pytest.mark.rhel_ver_match('8')
@pytest.mark.no_containers
def test_positive_search_by_reported_data(
    target_sat, rhel_contenthost, module_org, module_ak_with_cv
):
    """
    Search for host by reported data.
    For example, search by `reported.bios_vendor = SeaBIOS`.

    :id: 54341d00-34bc-11ef-a8a6-000c29a0e355

    :expectedresults: Return only hosts matching the reported data.

    :Verifies: SAT-9132

    :customerscenario: true
    """
    result = rhel_contenthost.register(module_org, None, module_ak_with_cv.name, target_sat)
    assert result.status == 0, f'Failed to register host: {result.stderr}'
    client = rhel_contenthost

    reported_data_params = [
        'bios_release_date',
        'bios_vendor',
        'bios_version',
    ]
    source_host = client.nailgun_host
    assert source_host.reported_data, f'Source host {client.hostname} does not report any data.'
    source_reported_data = source_host.reported_data

    with target_sat.ui_session() as session:
        session.organization.select(org_name=ANY_CONTEXT['org'])
        session.location.select(loc_name=ANY_CONTEXT['location'])

        for param_name in reported_data_params:
            param_value = source_reported_data[param_name]
            search_string = f'reported.{param_name} = {param_value}'
            api_hosts = target_sat.api.Host().search(query={'search': search_string})
            ui_hosts = session.host.search(search_string)
            assert set([host.name for host in api_hosts]) == set(
                [host['Name'] for host in ui_hosts]
            )


@pytest.mark.usefixtures('function_host')
def test_positive_search_by_configuration_status_alias(target_sat):
    """
    Search for host by new alias `configuration_status`.

    :id: 6af725d2-44fe-4b04-a8d6-ce8321a673d4

    :expectedresults: Searching hosts by original `status` and new alias `configuration_status`
        returns the same results.

    :Verifies: SAT-9132

    :customerscenario: true
    """
    status_search_term = Box(name='status', alias='configuration_status')
    search_params = [
        'enabled = true',
        'failed >= 0',
        'failed_restarts >= 0',
        'applied >= 0',
        'pending >= 0',
    ]

    with target_sat.ui_session() as session:
        session.organization.select(org_name=ANY_CONTEXT['org'])
        session.location.select(loc_name=ANY_CONTEXT['location'])

        for search_param in search_params:
            results = {}
            for search_term in status_search_term.values():
                search_string = f'{search_term}.{search_param}'
                results[search_term] = [host['Name'] for host in session.host.search(search_string)]
            assert results[status_search_term.name] == results[status_search_term.alias], (
                f'Different search results were found: {results}'
            )


def test_positive_search_by_parameter_with_different_values(
    session, module_org, smart_proxy_location, target_sat
):
    """Search for the host by global parameter assigned to it by its value

    :id: c3a4551e-d759-4a9d-ba90-8db4cab3db2c

    :expectedresults: Only one specific host is returned by search

    :BZ: 1725686
    """
    param_name = gen_string('alpha')
    param_values = [gen_string('alpha'), gen_string('alphanumeric')]
    hosts = [
        target_sat.api.Host(
            organization=module_org,
            location=smart_proxy_location,
            host_parameters_attributes=[{'name': param_name, 'value': param_value}],
        ).create()
        for param_value in param_values
    ]
    with session:
        # Check that hosts present in the system
        for host in hosts:
            assert session.host.search(host.name)[0]['Name'] == host.name
        # Check that search by parameter returns only one host in the list
        for param_value, host in zip(param_values, hosts, strict=True):
            values = session.host.search(f'params.{param_name} = {param_value}')
            assert len(values) == 1
            assert values[0]['Name'] == host.name


def test_positive_search_by_parameter_with_prefix(
    session, smart_proxy_location, target_sat, function_org
):
    """Search by global parameter assigned to host using prefix 'not' and
    any random string as parameter value to make sure that all hosts will
    be present in the list

    :id: a4affb90-1222-4d9a-94be-213f9e5be573

    :expectedresults: All assigned hosts to organization are returned by
        search
    """
    param_name = gen_string('alpha')
    param_value = gen_string('alpha')
    search_param_value = gen_string('alphanumeric')
    parameters = [{'name': param_name, 'value': param_value}]
    param_host = target_sat.api.Host(
        organization=function_org,
        location=smart_proxy_location,
        host_parameters_attributes=parameters,
    ).create()
    additional_host = target_sat.api.Host(
        organization=function_org, location=smart_proxy_location
    ).create()
    with session:
        session.organization.select(org_name=function_org.name)
        # Check that the hosts are present
        for host in [param_host, additional_host]:
            assert session.host.search(host.name)[0]['Name'] == host.name
        # Check that search by parameter with 'not' prefix returns both hosts
        values = session.host.search(f'not params.{param_name} = {search_param_value}')
        assert {value['Name'] for value in values} == {param_host.name, additional_host.name}


def test_positive_search_by_parameter_with_operator(
    session, smart_proxy_location, target_sat, function_org
):
    """Search by global parameter assigned to host using operator '<>' and
    any random string as parameter value to make sure that all hosts will
    be present in the list

    :id: 264065b7-0d04-467d-887a-0aba0d871b7c

    :expectedresults: All assigned hosts to organization are returned by
        search

    :BZ: 1463806
    """
    param_name = gen_string('alpha')
    param_value = gen_string('alpha')
    param_global_value = gen_string('numeric')
    search_param_value = gen_string('alphanumeric')
    target_sat.api.CommonParameter(name=param_name, value=param_global_value).create()
    parameters = [{'name': param_name, 'value': param_value}]
    param_host = target_sat.api.Host(
        organization=function_org,
        location=smart_proxy_location,
        host_parameters_attributes=parameters,
    ).create()
    additional_host = target_sat.api.Host(
        organization=function_org, location=smart_proxy_location
    ).create()
    with session:
        session.organization.select(org_name=function_org.name)
        # Check that the hosts are present
        for host in [param_host, additional_host]:
            assert session.host.search(host.name)[0]['Name'] == host.name
        # Check that search by parameter with '<>' operator returns both hosts
        values = session.host.search(f'params.{param_name} <> {search_param_value}')
        assert {value['Name'] for value in values} == {param_host.name, additional_host.name}


def test_positive_search_with_org_and_loc_context(
    session, target_sat, function_org, function_location
):
    """Perform usual search for host, but organization and location used
    for host create procedure should have 'All capsules' checkbox selected

    :id: 2ce50df0-2b30-42cc-a40b-0e1f4fde3c6f

    :expectedresults: Search functionality works as expected and correct
        result is returned

    :BZ: 1405496

    :customerscenario: true
    """
    host = target_sat.api.Host(organization=function_org, location=function_location).create()
    with session:
        session.organization.update(function_org.name, {'capsules.all_capsules': True})
        session.location.update(function_location.name, {'capsules.all_capsules': True})
        session.organization.select(org_name=function_org.name)
        session.location.select(loc_name=function_location.name)
        assert session.host.search(f'name = "{host.name}"')[0]['Name'] == host.name
        assert session.host.search(host.name)[0]['Name'] == host.name


def test_positive_search_by_org(session, smart_proxy_location, target_sat):
    """Search for host by specifying host's organization name

    :id: a3bb5bc5-cb9c-4b56-b383-f3e4d3d4d222

    :customerscenario: true

    :expectedresults: Search functionality works as expected and correct
        result is returned

    :BZ: 1447958
    """
    host = target_sat.api.Host(location=smart_proxy_location).create()
    org = host.organization.read()
    with session:
        session.organization.select(org_name=ANY_CONTEXT['org'])
        assert session.host.search(f'organization = "{org.name}"')[0]['Name'] == host.name


def test_positive_validate_inherited_cv_lce_ansiblerole(session, target_sat, module_host_template):
    """Create a host with hostgroup specified via CLI. Make sure host
    inherited hostgroup's lifecycle environment, content view and both
    fields are properly reflected via WebUI. Also host should be searchable by the
    inherited ansible role.

    :id: c83f6819-2649-4a8b-bb1d-ce93b2243765

    :expectedresults: Host's lifecycle environment, content view and ansible role match
       the ones specified in hostgroup.

    :customerscenario: true

    :BZ: 1391656, 2094912
    """
    SELECTED_ROLE = 'RedHatInsights.insights-client'
    cv_name = gen_string('alpha')
    lce_name = gen_string('alphanumeric')
    cv = target_sat.api_factory.cv_publish_promote(
        name=cv_name, env_name=lce_name, org_id=module_host_template.organization.id
    )
    lce = (
        target_sat.api.LifecycleEnvironment()
        .search(
            query={
                'search': f'name={lce_name} '
                f'and organization_id={module_host_template.organization.id}'
            }
        )[0]
        .read()
    )
    target_sat.cli.Ansible.roles_sync(
        {'role-names': SELECTED_ROLE, 'proxy-id': target_sat.nailgun_smart_proxy.id}
    )
    hostgroup = target_sat.cli_factory.hostgroup(
        {
            'content-view-id': cv.id,
            'lifecycle-environment-id': lce.id,
            'organization-ids': module_host_template.organization.id,
        }
    )
    result = target_sat.cli.HostGroup.ansible_roles_assign(
        {'name': hostgroup.name, 'ansible-roles': SELECTED_ROLE}
    )
    assert 'Ansible roles were assigned to the hostgroup' in result[0]['message']
    result = target_sat.cli.HostGroup.ansible_roles_add(
        {'name': hostgroup.name, 'ansible-role': SELECTED_ROLE}
    )
    assert 'Ansible role has been associated.' in result[0]['message']
    host = target_sat.cli_factory.make_host(
        {
            'architecture-id': module_host_template.architecture.id,
            'domain-id': module_host_template.domain.id,
            'hostgroup-id': hostgroup['id'],
            'location-id': module_host_template.location.id,
            'medium-id': module_host_template.medium.id,
            'operatingsystem-id': module_host_template.operatingsystem.id,
            'organization-id': module_host_template.organization.id,
            'partition-table-id': module_host_template.ptable.id,
        }
    )
    with session:
        values = session.host.read(host['name'], ['host.lce', 'host.content_view'])
        assert values['host']['lce'] == lce.name
        assert values['host']['content_view'] == cv.name
        matching_hosts = target_sat.api.Host().search(
            query={'search': f'ansible_role="{SELECTED_ROLE}"'}
        )
        assert len(matching_hosts), 'Host not found by inherited ansible role'
        assert host.name in [host.name for host in matching_hosts]


@pytest.mark.upgrade
def test_positive_bulk_delete_host(session, smart_proxy_location, target_sat, function_org):
    """Delete multiple hosts from the list

    :id: 8da2084a-8b50-46dc-b305-18eeb80d01e0

    :expectedresults: All selected hosts should be deleted successfully

    :BZ: 1368026
    """
    host_template = target_sat.api.Host(organization=function_org, location=smart_proxy_location)
    host_template.create_missing()
    hosts_names = [
        target_sat.api.Host(
            organization=function_org,
            location=smart_proxy_location,
            root_pass=host_template.root_pass,
            architecture=host_template.architecture,
            domain=host_template.domain,
            medium=host_template.medium,
            operatingsystem=host_template.operatingsystem,
            ptable=host_template.ptable,
        )
        .create()
        .name
        for _ in range(3)
    ]
    with session:
        session.organization.select(org_name=function_org.name)
        values = session.host.read_all()
        assert len(hosts_names) == len(values['table'])
        session.host.delete_hosts('All')
        values = session.host.read_all()
        assert not values['table']


# ------------------------------ NEW HOST UI DETAILS ----------------------------
def test_positive_read_details_page_from_new_ui(session, host_ui_options):
    """Create new Host and read all its content through details page

    :id: ef0c5942-9049-11ec-8029-98fa9b6ecd5a

    :expectedresults: Host is created and has expected content
    """
    with session:
        api_values, host_name = host_ui_options
        session.location.select(api_values['host.location'])
        session.host_new.create(api_values)
        assert session.host_new.search(host_name)[0]['Name'] == host_name
        values = session.host_new.get_details(host_name, widget_names='overview')
        assert values['overview']['host_status']['status'] == 'All statuses OK'
        assert (
            values['overview']['details']['details']['mac_address']
            == api_values['interfaces.interface.mac']
        )
        user = session.host_new.get_details(host_name, widget_names='current_user')['current_user']
        assert values['overview']['details']['details']['host_owner'] == user
        assert values['overview']['details']['details']['comment'] == 'Host with fake data'


def test_positive_manage_table_columns(
    target_sat, test_name, ui_hosts_columns_user, current_sat_org, current_sat_location
):
    """Set custom columns of the hosts table.

    :id: e5e18982-cc43-11ed-8562-000c2989e153

    :steps:
        1. Navigate to the Hosts page.
        2. Switch to default organization and location, where is at least one host (Satellite).
        3. Set custom columns for the hosts table via the 'Manage columns' dialog.

    :expectedresults: Check if the custom columns were set properly, i.e., are displayed
        or not displayed in the table.

    :BZ: 1813274, 2212499

    :customerscenario: true
    """
    columns = {
        'Host group': False,
        'Last report': False,
        'Comment': False,
        'Installable updates': True,
        'RHEL Lifecycle status': False,
        'Registered': True,
        'Last checkin': True,
        'IPv4': True,
        'MAC': True,
        'Sockets': True,
        'Cores': True,
        'RAM': True,
        'Boot time': True,
        'Recommendations': False,
    }
    with target_sat.ui_session(
        test_name, ui_hosts_columns_user.login, ui_hosts_columns_user.password
    ) as session:
        session.organization.select(org_name=current_sat_org.name)
        session.location.select(loc_name=current_sat_location.name)
        session.host.manage_table_columns(columns)
        displayed_columns = session.host.get_displayed_table_headers()
        for column, is_displayed in columns.items():
            assert (column in displayed_columns) is is_displayed


def test_all_hosts_manage_columns(target_sat, new_host_ui):
    """Verify that the manage columns widget changes the columns appropriately

    :id: 5e13267a-68d2-451a-ae00-6502dd5db7f4

    :expectedresults: Through the widget you can change the columns on the All Hosts page

    :CaseComponent: Hosts-Content

    :Team: Phoenix-subscriptions

    :Verifies: SAT-19064
    """
    columns = {
        'Host group': True,
        'Last report': True,
        'Comment': True,
        'IPv4': True,
        'MAC': True,
        'Sockets': True,
        'Cores': True,
        'RAM': True,
        'Boot time': True,
    }
    with target_sat.ui_session() as session:
        # Small workaround for an existing bug, reloads the page
        session.all_hosts.get_displayed_table_headers()
        wait_for(lambda: session.browser.refresh(), timeout=5)
        session.all_hosts.manage_table_columns(columns)
        displayed_columns = session.all_hosts.get_displayed_table_headers()
        for column, is_displayed in columns.items():
            assert (column in displayed_columns) is is_displayed


def test_positive_host_details_read_templates(
    session, target_sat, current_sat_org, current_sat_location
):
    """Check if all assigned host provisioning templates are correctly reported
    in host detail / Details tab / Provisioning templates card.

    :id: 43ca722e-d28a-11ed-8970-000c2989e153

    :steps:
        1. Go to Hosts page and select the Satellite host machine.
        2. Go to the Details tab.
        3. Gather all names from the `Provisioning templates` card.
        4. Compare them with the host provisioning templates obtained via API.

    :expectedresults: Provisioning templates reported via API and in UI should match.

    :BZ: 2128038

    :customerscenario: true
    """
    host = target_sat.api.Host().search(query={'search': f'name={target_sat.hostname}'})[0]
    api_templates = [template['name'] for template in host.list_provisioning_templates()]
    with session:
        session.organization.select(org_name=current_sat_org.name)
        session.location.select(loc_name=current_sat_location.name)
        host_detail = session.host_new.get_details(target_sat.hostname, widget_names='details')
        ui_templates = [
            row['column1'].strip()
            for row in host_detail['details']['provisioning_templates']['templates_table']
        ]
    assert set(api_templates) == set(ui_templates)


@pytest.mark.rhel_ver_match('8')
@pytest.mark.no_containers
@pytest.mark.parametrize(
    'module_repos_collection_with_setup',
    [
        {
            'distro': 'rhel8',
            'YumRepository': {'url': settings.repos.yum_3.url},
        }
    ],
    ids=['yum3'],
    indirect=True,
)
def test_positive_update_delete_package(
    session,
    target_sat,
    rhel_contenthost,
    module_repos_collection_with_setup,
):
    """Update a package on a host using the new Content tab

    :id: ffc19a40-85f4-4894-a18b-f6d88b2ce377

    :steps:
        1. Navigate to the Content tab.
        2. Disable repository set
        3. Package from repository cannot be installed
        4. Enable repository set
        5. Install a package on a registered host.
        6. Downgrade package version
        7. Check if the package is in an upgradable state.
        8. Select package and upgrade via rex.
        9. Delete the package

    :expectedresults: The package is updated and deleted
    """
    client = rhel_contenthost
    client.add_rex_key(target_sat)
    module_repos_collection_with_setup.setup_virtual_machine(
        vm=client,
        enable_custom_repos=True,
    )
    with session:
        session.location.select(loc_name=DEFAULT_LOC)
        product_name = module_repos_collection_with_setup.custom_product.name

        session.host_new.override_repo_sets(client.hostname, product_name, "Override to disabled")
        repos = session.host_new.get_repo_sets(client.hostname, product_name)
        assert repos[0]['Status'] == 'Disabled'
        result = client.run(f'yum install -y {FAKE_7_CUSTOM_PACKAGE}')
        assert result.status != 0
        session.host_new.override_repo_sets(client.hostname, product_name, "Override to enabled")
        repos = session.host_new.get_repo_sets(client.hostname, product_name)
        assert repos[0]['Status'] == 'Enabled'
        # refresh repos on system
        client.run('subscription-manager repos')
        # install package
        session.host_new.install_package(client.hostname, FAKE_8_CUSTOM_PACKAGE_NAME)
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Install package(s) on {client.hostname}'),
            search_rate=4,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        packages = session.host_new.get_packages(client.hostname, FAKE_8_CUSTOM_PACKAGE_NAME)
        assert len(packages) == 1
        assert packages[0]['Package'] == FAKE_8_CUSTOM_PACKAGE_NAME
        assert 'Up-to date' in packages[0]['Status']
        result = client.run(f'rpm -q {FAKE_8_CUSTOM_PACKAGE}')
        assert result.status == 0

        # downgrade package version
        client.run(f'yum -y downgrade {FAKE_8_CUSTOM_PACKAGE_NAME}')
        result = client.run(f'rpm -q {FAKE_8_CUSTOM_PACKAGE_NAME}')
        assert result.status == 0

        # this should reload page to update packages table
        session.host_new.get_details(client.hostname, widget_names='overview')

        # filter packages
        packages = session.host_new.get_packages(client.hostname, FAKE_8_CUSTOM_PACKAGE_NAME)
        assert len(packages) == 1
        assert packages[0]['Package'] == FAKE_8_CUSTOM_PACKAGE_NAME
        assert 'Upgradable' in packages[0]['Status']

        # update package
        session.host_new.apply_package_action(
            client.hostname, FAKE_8_CUSTOM_PACKAGE_NAME, "Upgrade via remote execution"
        )
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Update package(s) {FAKE_8_CUSTOM_PACKAGE_NAME} on {client.hostname}'),
            search_rate=2,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        packages = session.host_new.get_packages(client.hostname, FAKE_8_CUSTOM_PACKAGE_NAME)
        assert 'Up-to date' in packages[0]['Status']

        # remove package
        session.host_new.apply_package_action(client.hostname, FAKE_8_CUSTOM_PACKAGE_NAME, "Remove")
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Remove package(s) {FAKE_8_CUSTOM_PACKAGE_NAME} on {client.hostname}'),
            search_rate=2,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        packages = session.host_new.get_packages(client.hostname, FAKE_8_CUSTOM_PACKAGE_NAME)
        assert not packages
        result = client.run(f'rpm -q {FAKE_8_CUSTOM_PACKAGE}')
        assert result.status != 0


@pytest.mark.rhel_ver_match('8')
@pytest.mark.no_containers
@pytest.mark.parametrize(
    'module_repos_collection_with_setup',
    [
        {
            'distro': 'rhel8',
            'YumRepository': {'url': settings.repos.yum_3.url},
        }
    ],
    ids=['yum3'],
    indirect=True,
)
def test_positive_apply_erratum(
    session,
    target_sat,
    rhel_contenthost,
    module_repos_collection_with_setup,
):
    """Apply an erratum on a host using the new Errata tab

    :id: 328e629a-f261-4dc1-ad6f-def27e2fcf07

    :setup:
        1. Valid yum repo with an applicable erratum.

    :steps:
        1. Install a package on a registered host.
        2. Check the Errata card on the Overview tab
        3. Navigate to the Errata tab.
        4. Check for applicable errata.
        5. Select errata and apply via rex.

    :expectedresults: The erratum is applied
    """
    # install package
    client = rhel_contenthost
    client.add_rex_key(target_sat)
    module_repos_collection_with_setup.setup_virtual_machine(client, target_sat)
    errata_id = settings.repos.yum_3.errata[25]
    client.run(f'yum install -y {FAKE_7_CUSTOM_PACKAGE}')
    result = client.run(f'rpm -q {FAKE_7_CUSTOM_PACKAGE}')
    assert result.status == 0
    with session:
        session.location.select(loc_name=DEFAULT_LOC)
        assert session.host_new.search(client.hostname)[0]['Name'] == client.hostname
        # read widget on overview page
        values = session.host_new.get_details(client.hostname, widget_names='overview')['overview']
        assert values['installable_errata']['security_advisory'] == '1 security advisory'
        assert values['installable_errata']['enhancements'] == '1 enhancement'
        # read errata tab
        values = session.host_new.get_details(client.hostname, widget_names='content.errata')
        assert len(values['content']['errata']['table']) == 2
        # filter just security erratum
        erratas = session.host_new.get_errata_by_type(client.hostname, 'Security')
        assert len(erratas['content']['errata']['table']) == 1
        assert erratas['content']['errata']['table'][0]['Errata'] == errata_id
        # apply errata
        session.host_new.apply_erratas(client.hostname, f"errata_id == {errata_id}")
        task_result = target_sat.wait_for_tasks(
            search_query=(
                f'"Install errata errata_id == {errata_id.lower()} '
                f'and type=security on {client.hostname}"'
            ),
            search_rate=2,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        # verify
        values = session.host_new.get_details(client.hostname, widget_names='content.errata')
        assert 'table' not in values['content']['errata']
        result = client.run(
            'yum update --assumeno --security | grep "No packages needed for security"'
        )
        assert result.status == 1


@pytest.mark.e2e
@pytest.mark.rhel_ver_match('8')
@pytest.mark.no_containers
@pytest.mark.parametrize(
    'module_repos_collection_with_setup',
    [
        {
            'distro': 'rhel8',
            'YumRepository': {'url': settings.repos.module_stream_1.url},
        }
    ],
    ids=['module_stream_1'],
    indirect=True,
)
def test_positive_crud_module_streams(
    session,
    target_sat,
    rhel_contenthost,
    module_repos_collection_with_setup,
):
    """CRUD test for the Module streams new UI tab

    :id: 9800a006-49cc-4c0a-aed8-6a32c4bf0eab

    :setup:
        1. Valid yum repo with Module Streams.

    :steps:
        1. Create Yum Repository which contains module-streams as URL
        2. Enable Module stream
        3. Install Module stream
        4. Delete the Module stream
        5. Reset the Module stream

    :expectedresults: Module streams can be enabled, installed, removed and reset using the new UI.
    """
    module_name = 'duck'
    client = rhel_contenthost
    client.add_rex_key(target_sat)
    module_repos_collection_with_setup.setup_virtual_machine(client, target_sat)
    with session:
        session.location.select(loc_name=DEFAULT_LOC)
        streams = session.host_new.get_module_streams(client.hostname, module_name)
        assert streams[0]['Name'] == module_name
        assert streams[0]['State'] == 'Default'

        # enable module stream
        session.host_new.apply_module_streams_action(client.hostname, module_name, "Enable")
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Module enable {module_name} on {client.hostname}'),
            search_rate=5,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        streams = session.host_new.get_module_streams(client.hostname, module_name)
        assert streams[0]['State'] == 'Enabled'
        assert streams[0]['Installation status'] == 'Not installed'

        # install
        session.host_new.apply_module_streams_action(client.hostname, module_name, "Install")
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Module install {module_name} on {client.hostname}'),
            search_rate=5,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        streams = session.host_new.get_module_streams(client.hostname, module_name)
        assert streams[0]['Installation status'] == 'Up-to-date'

        # remove
        session.host_new.apply_module_streams_action(client.hostname, module_name, "Remove")
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Module remove {module_name} on {client.hostname}'),
            search_rate=5,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        streams = session.host_new.get_module_streams(client.hostname, module_name)
        assert streams[0]['State'] == 'Enabled'
        assert streams[0]['Installation status'] == 'Not installed'

        session.host_new.apply_module_streams_action(client.hostname, module_name, "Reset")
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Module reset {module_name} on {client.hostname}'),
            search_rate=5,
            max_tries=60,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        # this should reload page to update module streams table
        session.host_new.get_details(client.hostname, widget_names='overview')
        streams = session.host_new.get_module_streams(client.hostname, module_name)
        assert streams[0]['State'] == 'Default'
        assert streams[0]['Installation status'] == 'Not installed'


# ------------------------------ PUPPET ENABLED SAT TESTS ----------------------------
@pytest.fixture(scope='module')
def module_puppet_enabled_proxy_with_loc(
    session_puppet_enabled_sat, module_puppet_loc, session_puppet_enabled_proxy
):
    session_puppet_enabled_proxy.location.append(
        session_puppet_enabled_sat.api.Location(id=module_puppet_loc.id)
    )
    session_puppet_enabled_proxy.update(['location'])


def test_positive_inherit_puppet_env_from_host_group_when_action(
    session_puppet_enabled_sat, module_puppet_org, module_puppet_loc, module_puppet_environment
):
    """Host group puppet environment is inherited to already created
    host when corresponding action is applied to that host

    :id: 3f5af54e-e259-46ad-a2af-7dc1850891f5

    :customerscenario: true

    :expectedresults: Expected puppet environment is inherited to the host

    :BZ: 1414914
    """
    host = session_puppet_enabled_sat.api.Host(
        organization=module_puppet_org, location=module_puppet_loc
    ).create()
    hostgroup = session_puppet_enabled_sat.api.HostGroup(
        environment=module_puppet_environment,
        organization=[module_puppet_org],
        location=[module_puppet_loc],
    ).create()
    with session_puppet_enabled_sat.ui_session() as session:
        session.organization.select(org_name=module_puppet_org.name)
        session.location.select(loc_name=module_puppet_loc.name)
        session.host.apply_action(
            'Change Environment', [host.name], {'environment': '*Clear environment*'}
        )
        values = session.host.read(host.name, widget_names='host')
        assert values['host']['hostgroup'] == ''
        assert values['host']['puppet_environment'] == ''
        session.host.apply_action('Change Group', [host.name], {'host_group': hostgroup.name})
        values = session.host.read(host.name, widget_names='host')
        assert values['host']['hostgroup'] == hostgroup.name
        assert values['host']['puppet_environment'] == ''
        session.host.apply_action(
            'Change Environment', [host.name], {'environment': '*Inherit from host group*'}
        )
        assert (
            session.host.get_details(host.name)['properties']['properties_table'][
                'Puppet Environment'
            ]
            == module_puppet_environment.name
        )
        values = session.host.read(host.name, widget_names='host')
        assert values['host']['hostgroup'] == hostgroup.name
        assert values['host']['puppet_environment'] == module_puppet_environment.name


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
@pytest.mark.usefixtures('module_puppet_enabled_proxy_with_loc')
def test_positive_create_with_puppet_class(
    session_puppet_enabled_sat,
    module_puppet_loc,
    module_puppet_org,
    module_env_search,
    module_import_puppet_module,
    module_puppet_enabled_proxy_with_loc,
):
    """Create new Host with puppet class assigned to it

    :id: d883f169-1105-435c-8422-a7160055734a

    :expectedresults: Host is created and contains correct puppet class
    """

    host_template = session_puppet_enabled_sat.api.Host(
        organization=module_puppet_org, location=module_puppet_loc
    )
    host_template.create_missing()
    host_name = f'{host_template.name}.{host_template.domain.name}'
    os_name = f'{host_template.operatingsystem.name} {host_template.operatingsystem.major}'
    values = {
        'host.name': host_template.name,
        'host.organization': host_template.organization.name,
        'host.location': host_template.location.name,
        'host.lce': ENVIRONMENT,
        'host.content_view': DEFAULT_CV,
        'operating_system.architecture': host_template.architecture.name,
        'operating_system.operating_system': os_name,
        'operating_system.media_type': 'All Media',
        'operating_system.media': host_template.medium.name,
        'operating_system.ptable': host_template.ptable.name,
        'operating_system.root_password': host_template.root_pass,
        'interfaces.interface.interface_type': 'Interface',
        'interfaces.interface.device_identifier': gen_string('alpha'),
        'interfaces.interface.mac': host_template.mac,
        'interfaces.interface.domain': host_template.domain.name,
        'interfaces.interface.primary': True,
        'interfaces.interface.interface_additional_data.virtual_nic': False,
        'parameters.global_params': None,
        'parameters.host_params': None,
        'additional_information.comment': 'Host with fake data',
        'host.puppet_environment': module_env_search.name,
        'puppet_enc.classes.assigned': [module_import_puppet_module['puppet_class']],
    }
    with session_puppet_enabled_sat.ui_session() as session:
        session.organization.select(org_name=module_puppet_org.name)
        session.location.select(loc_name=ANY_CONTEXT['location'])
        session.host.create(values)
        assert session.host.search(host_name)[0]['Name'] == host_name
        values = session.host.read(host_name, widget_names='puppet_enc')
        assert len(values['puppet_enc']['classes']['assigned']) == 1
        assert (
            values['puppet_enc']['classes']['assigned'][0]
            == module_import_puppet_module['puppet_class']
        )


def test_positive_inherit_puppet_env_from_host_group_when_create(
    session_puppet_enabled_sat, module_env_search, module_puppet_org, module_puppet_loc
):
    """Host group puppet environment is inherited to host in create
    procedure

    :id: 05831ecc-3132-4eb7-ad90-155470f331b6

    :customerscenario: true

    :expectedresults: Expected puppet environment is inherited to the form

    :BZ: 1414914
    """

    hg_name = gen_string('alpha')
    with session_puppet_enabled_sat.ui_session() as session:
        session.organization.select(org_name=module_puppet_org.name)
        session.location.select(loc_name=module_puppet_loc.name)
        session.hostgroup.create(
            {'host_group.name': hg_name, 'host_group.puppet_environment': module_env_search.name}
        )
        assert session.hostgroup.search(hg_name)[0]['Name'] == hg_name
        values = session.host.helper.read_create_view(
            {}, ['host.puppet_environment', 'host.inherit_puppet_environment']
        )
        assert not values['host']['puppet_environment']
        assert values['host']['inherit_puppet_environment'] is False
        values = session.host.helper.read_create_view(
            {'host.hostgroup': hg_name},
            ['host.puppet_environment', 'host.inherit_puppet_environment'],
        )
        assert values['host']['puppet_environment'] == module_env_search.name
        assert values['host']['inherit_puppet_environment'] is True
        values = session.host.helper.read_create_view(
            {'host.inherit_puppet_environment': False},
            ['host.puppet_environment', 'host.inherit_puppet_environment'],
        )
        assert values['host']['puppet_environment'] == module_env_search.name
        assert values['host']['inherit_puppet_environment'] is False


@pytest.mark.usefixtures('module_puppet_enabled_proxy_with_loc')
def test_positive_set_multi_line_and_with_spaces_parameter_value(
    session_puppet_enabled_sat,
    module_puppet_org,
    module_puppet_loc,
    module_puppet_published_cv,
    module_puppet_lce_library,
):
    """Check that host parameter value with multi-line and spaces is
    correctly represented in yaml format

    :id: d72b481d-2279-4478-ab2d-128f92c76d9c

    :customerscenario: true

    :expectedresults:
        1. parameter is correctly represented in yaml format without
           line break (special chars should be escaped)
        2. host parameter value is the same when restored from yaml format

    :BZ: 1315282
    """
    host_template = session_puppet_enabled_sat.api.Host(
        organization=module_puppet_org, location=module_puppet_loc
    )
    host_template.create_missing()

    param_name = gen_string('alpha').lower()
    # long string that should be escaped and affected by line break with
    # yaml dump by default
    param_value = (
        'auth                          include              '
        'password-auth\r\n'
        'account     include                  password-auth'
    )
    host = session_puppet_enabled_sat.api.Host(
        organization=host_template.organization,
        architecture=host_template.architecture,
        domain=host_template.domain,
        location=host_template.location,
        mac=host_template.mac,
        medium=host_template.medium,
        operatingsystem=host_template.operatingsystem,
        ptable=host_template.ptable,
        root_pass=host_template.root_pass,
        content_facet_attributes={
            'content_view_id': module_puppet_published_cv.id,
            'lifecycle_environment_id': module_puppet_lce_library.id,
        },
    ).create()
    with session_puppet_enabled_sat.ui_session() as session:
        session.organization.select(org_name=module_puppet_org.name)
        session.location.select(loc_name=module_puppet_loc.name)
        session.host.update(
            host.name, {'parameters.host_params': [dict(name=param_name, value=param_value)]}
        )
        yaml_text = session.host.read_yaml_output(host.name)
        # ensure parameter value is represented in yaml format without
        # line break (special chars should be escaped)
        assert param_value.encode('unicode_escape') in bytes(yaml_text, 'utf-8')
        # host parameter value is the same when restored from yaml format
        yaml_content = yaml.load(yaml_text, yaml.SafeLoader)
        host_parameters = yaml_content.get('parameters')
        assert host_parameters
        assert param_name in host_parameters
        assert host_parameters[param_name] == param_value


@pytest.mark.pit_client
@pytest.mark.rhel_ver_match('[7,8,9]')
def test_positive_tracer_enable_reload(tracer_install_host, target_sat):
    """Using the new Host UI,enable tracer and verify that the page reloads

    :id: c9ebd4a8-6db3-4d0e-92a2-14951c26769b

    :CaseComponent: katello-tracer

    :Team: Endeavour

    :steps:
        1. Register a RHEL host to Satellite.
        2. Prepare katello-tracer to be installed
        3. Navigate to the Traces tab in New Host UI
        4. Enable tracer using the popup

    :expectedresults: The Tracer tab message updates accordingly during the process, and displays
        the state the correct Title
    """
    host = (
        target_sat.api.Host().search(query={'search': tracer_install_host.hostname})[0].read_json()
    )
    with target_sat.ui_session() as session:
        session.organization.select(host['organization_name'])
        tracer_title = session.host_new.get_tracer_tab_title(tracer_install_host.hostname)
        assert tracer_title == "Traces are not enabled"
        session.host_new.enable_tracer(tracer_install_host.hostname)
        timestamp = (datetime.now(UTC) - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')
        target_sat.wait_for_tasks(
            search_query='action = "Run hosts job: Install package(s) katello-host-tools-tracer"'
            f' and started_at >= "{timestamp}"',
            search_rate=15,
            max_tries=10,
        )
        tracer_title = session.host_new.get_tracer_tab_title(tracer_install_host.hostname)
        assert tracer_title == "No applications to restart"


def test_all_hosts_delete(target_sat, function_org, function_location, new_host_ui):
    """Create a host and delete it through All Hosts UI

    :id: 42b4560c-bb57-4c58-928e-e5fd5046b93f

    :expectedresults: Successful deletion of a host through the table dropdown

    :CaseComponent:Hosts-Content

    :Team: Phoenix-subscriptions
    """
    host = target_sat.api.Host(organization=function_org, location=function_location).create()
    with target_sat.ui_session() as session:
        session.organization.select(function_org.name)
        session.location.select(function_location.name)
        # Get current headers
        headers = session.all_hosts.get_displayed_table_headers()
        stripped_headers = tuple(
            header for header in headers if header is not None and header != 'Name'
        )
        wait_for(lambda: session.browser.refresh(), timeout=5)
        # Make sure there is only Name column displayed
        session.all_hosts.manage_table_columns({header: False for header in stripped_headers})
        assert session.all_hosts.delete(host.name)
        # Get table to original state
        wait_for(lambda: session.browser.refresh(), timeout=5)
        session.all_hosts.manage_table_columns({header: True for header in stripped_headers})


def test_all_hosts_bulk_delete(target_sat, function_org, function_location, new_host_ui):
    """Create several hosts, and delete them via Bulk Actions in All Hosts UI

    :id: af1b4a66-dd83-47c3-904b-e8627119cc53

    :expectedresults: Successful deletion of multiple hosts at once through Bulk Action

    :CaseComponent:Hosts-Content

    :Team: Phoenix-subscriptions
    """
    for _ in range(10):
        target_sat.api.Host(organization=function_org, location=function_location).create()
    with target_sat.ui_session() as session:
        session.organization.select(function_org.name)
        session.location.select(function_location.name)
        assert session.all_hosts.bulk_delete_all()


def test_all_hosts_bulk_cve_reassign(
    target_sat, module_org, module_location, module_lce, module_cv, new_host_ui
):
    """Create several hosts, and bulk assigns them a new CVE via All Hosts UI

    :id: 9acb3cf3-c042-4cc7-abdf-31f9a7f1fff0

    :steps:
        1.Create 2 Hosts, and register them to the first LCE.
        2.Create a second LCE and promote the CV from the first LCE to this one.
        3.Using the All Hosts UI, reassign both hosts from the first LCE to the second LCE.

    :expectedresults: Both hosts are successfully assigned to a new LCE and CV

    :CaseComponent: Hosts-Content

    :Team: Phoenix-subscriptions
    """
    lce2 = target_sat.api.LifecycleEnvironment(organization=module_org).create()
    module_cv = target_sat.api.ContentView(id=module_cv.id).read()
    module_cv = cv_publish_promote(target_sat, module_org, module_cv, module_lce)['content-view']
    module_cv = cv_publish_promote(target_sat, module_org, module_cv, lce2)['content-view']
    for _ in range(3):
        target_sat.api.Host(
            organization=module_org,
            location=module_location,
            content_facet_attributes={
                'content_view_id': module_cv.id,
                'lifecycle_environment_id': module_lce.id,
            },
        ).create()
    with target_sat.ui_session() as session:
        session.organization.select(module_org.name)
        session.location.select(module_location.name)
        headers = session.all_hosts.get_displayed_table_headers()
        if "Lifecycle environment" not in headers:
            wait_for(lambda: session.browser.refresh(), timeout=5)
            session.all_hosts.manage_table_columns(
                {
                    'Lifecycle environment': True,
                }
            )
        pre_table = session.all_hosts.read_table()
        for row in pre_table:
            assert row['Lifecycle environment'] == module_lce.name
        session.all_hosts.manage_cve(lce=lce2.name, cv=module_cv.name)
        wait_for(lambda: session.browser.refresh(), timeout=5)
        post_table = session.all_hosts.read_table()
        for row in post_table:
            assert row['Lifecycle environment'] == lce2.name


def test_all_hosts_redirect_button(target_sat):
    """Verify that the New UI button on the old Host page correctly redirects
    to the All Hosts UI

    :id: 7256f6d0-3ad9-471c-9e3e-bd41cc00a217

    :expectedresults: New UI Button redirects to All Hosts page

    :CaseComponent: Hosts-Content

    :Team: Phoenix-subscriptions
    """
    with target_sat.ui_session() as session:
        url = session.host.new_ui_button()
        assert "/new/hosts" in url


def test_all_hosts_bulk_build_management(target_sat, function_org, function_location, new_host_ui):
    """Create several hosts, and manage them via Build Management in All Host UI

    :id: fff71945-6534-45cf-88a6-16b25c060f0a

    :expectedresults: Build Management dropdown in All Hosts UI works properly.

    :CaseComponent:Hosts-Content

    :Team: Phoenix-subscriptions
    """
    for _ in range(3):
        target_sat.api.Host(organization=function_org, location=function_location).create()
    with target_sat.ui_session() as session:
        session.organization.select(function_org.name)
        session.location.select(function_location.name)
        assert 'Success alert: Built 3 hosts' in session.all_hosts.build_management()
        assert (
            'Success alert: 3 hosts set to build and rebooting.'
            in session.all_hosts.build_management(reboot=True)
        )
        assert 'Rebuilt configuration for 3 hosts' in session.all_hosts.build_management(
            rebuild=True
        )


def test_bootc_booted_container_images(target_sat, bootc_host, function_ak_with_cv, function_org):
    """Create a bootc host, and read its information via the Booted Container Images UI

    :id: c15f02a2-05e0-447a-bbcc-aace08d40d1a

    :expectedresults: Booted Container Images contains the correct information for a given booted image

    :CaseComponent:Hosts-Content

    :Verifies:SAT-27163

    :Team: Phoenix-subscriptions
    """
    bootc_dummy_info = json.loads(DUMMY_BOOTC_FACTS)
    assert bootc_host.register(function_org, None, function_ak_with_cv.name, target_sat).status == 0
    assert bootc_host.subscribed

    with target_sat.ui_session() as session:
        session.organization.select(function_org.name)
        booted_container_image_info = session.bootc.read(bootc_dummy_info['bootc.booted.image'])
        assert (
            booted_container_image_info[0]['Image name'] == bootc_dummy_info['bootc.booted.image']
        )
        assert booted_container_image_info[0]['Image digests'] == '1'
        assert booted_container_image_info[0]['Hosts'] == '1'
        assert (
            booted_container_image_info[1]['Image digest']
            == bootc_dummy_info['bootc.booted.digest']
        )
        assert booted_container_image_info[1]['Hosts'] == '1'


def test_bootc_host_details(target_sat, bootc_host, function_ak_with_cv, function_org):
    """Create a bootc host, and read it's information via the Host Details UI

    :id: 842356e9-8798-421d-aca6-0a1774c3f22b

    :expectedresults: Host Details UI contains the proper information for a bootc host

    :CaseComponent:Hosts-Content

    :Verifies:SAT-27171

    :Team: Phoenix-subscriptions
    """
    bootc_dummy_info = json.loads(DUMMY_BOOTC_FACTS)
    assert bootc_host.register(function_org, None, function_ak_with_cv.name, target_sat).status == 0
    assert bootc_host.subscribed

    with target_sat.ui_session() as session:
        session.organization.select(function_org.name)
        values = session.host_new.get_details(bootc_host.hostname, widget_names='details.bootc')
        assert (
            values['details']['bootc']['details']['running_image']
            == bootc_dummy_info['bootc.booted.image']
        )
        assert (
            values['details']['bootc']['details']['running_image_digest']
            == bootc_dummy_info['bootc.booted.digest']
        )
        assert (
            values['details']['bootc']['details']['rollback_image']
            == bootc_dummy_info['bootc.rollback.image']
        )
        assert (
            values['details']['bootc']['details']['rollback_image_digest']
            == bootc_dummy_info['bootc.rollback.digest']
        )


def test_bootc_rex_job(target_sat, bootc_host, function_ak_with_cv, function_org):
    """Run all bootc rex job (switch, upgrade, rollback, status) through Host Details UI

    :id: ef92a5f7-8cc7-4849-822c-90ea68b10554

    :expectedresults: Host Details UI links to the proper template, which runs successfully for all templates

    :CaseComponent: Hosts-Content

    :Verifies:SAT-27154, SAT-27158

    :Team: Phoenix-subscriptions
    """
    BOOTC_SWITCH_TARGET = "images.paas.redhat.com/bootc/rhel-bootc:latest-10.0"
    BOOTC_BASE_IMAGE = "localhost/tpl-bootc-rhel-10.0:latest"
    assert bootc_host.register(function_org, None, function_ak_with_cv.name, target_sat).status == 0
    assert bootc_host.subscribed

    with target_sat.ui_session() as session:
        session.organization.select(function_org.name)
        # bootc status
        session.host_new.run_bootc_job(bootc_host.hostname, 'status')
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Remote action: Run Bootc status on {bootc_host.hostname}'),
            search_rate=2,
            max_tries=30,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        assert f'image: {BOOTC_BASE_IMAGE}' in task_status['humanized']['output']
        assert 'Successfully updated the system facts.' in task_status['humanized']['output']
        # bootc switch
        session.host_new.run_bootc_job(
            bootc_host.hostname, 'switch', job_options=BOOTC_SWITCH_TARGET
        )
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Remote action: Run Bootc switch on {bootc_host.hostname}'),
            search_rate=2,
            max_tries=30,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        assert 'Successfully updated the system facts.' in task_status['humanized']['output']
        assert f'Queued for next boot: {BOOTC_SWITCH_TARGET}' in task_status['humanized']['output']
        # bootc upgrade
        session.host_new.run_bootc_job(bootc_host.hostname, 'upgrade')
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Remote action: Run Bootc upgrade on {bootc_host.hostname}'),
            search_rate=2,
            max_tries=30,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        assert 'Successfully updated the system facts.' in task_status['humanized']['output']
        assert f'No changes in {BOOTC_SWITCH_TARGET}' in task_status['humanized']['output']
        # reboot the host, to ensure there is a rollback image
        bootc_host.execute('reboot')
        bootc_host.wait_for_connection()
        # bootc rollback
        session.host_new.run_bootc_job(bootc_host.hostname, 'rollback')
        task_result = target_sat.wait_for_tasks(
            search_query=(f'Remote action: Run Bootc rollback on {bootc_host.hostname}'),
            search_rate=2,
            max_tries=30,
        )
        task_status = target_sat.api.ForemanTask(id=task_result[0].id).poll()
        assert task_status['result'] == 'success'
        assert 'Next boot: rollback deployment' in task_status['humanized']['output']
        assert 'Successfully updated the system facts.' in task_status['humanized']['output']
        # Check that the display in host details matches the task output
        values = session.host_new.get_details(bootc_host.hostname, widget_names='details.bootc')
        assert values
        assert values['details']['bootc']['details']['running_image'] == BOOTC_SWITCH_TARGET
        assert values['details']['bootc']['details']['rollback_image'] == BOOTC_BASE_IMAGE


@pytest.fixture(scope='module')
def change_content_source_prep(
    module_target_sat,
    module_sca_manifest_org,
    module_capsule_configured,
    module_location,
):
    """
    This fixture sets up all the necessary entities for tests
    exercising the Change of the hosts's content source.

     It creates a new product in the organization,
     creates a new repository in the product,
     creates a new lce,
     creates a new CV in the organization, adds the repository to the CV,
     publishes the CV, and promotes the published version to the lifecycle environment,
     creates a new activation key for the CV in the lce,
     registers the RHEL content host with the activation key,
     updates the capsule's taxonomies
     adds the lifecycle environment to the capsule's content.

     Fixture returns module_target_sat, org, lce, capsule, content_view, loc, ak
    """
    product_name, lce_name = (gen_string('alpha') for _ in range(2))

    org = module_sca_manifest_org
    loc = module_location

    product = module_target_sat.api.Product(
        name=product_name,
        organization=org.id,
    ).create()

    repository = module_target_sat.api.Repository(
        product=product,
        content_type=REPO_TYPE['file'],
        url=CUSTOM_FILE_REPO,
    ).create()

    lce = module_target_sat.cli_factory.make_lifecycle_environment(
        {'name': lce_name, 'organization-id': org.id}
    )

    # Create CV
    content_view = module_target_sat.api.ContentView(organization=org.id).create()
    # Add repos to CV
    content_view.repository = [repository]
    content_view = content_view.update(['repository'])
    # Publish that CV and promote it
    content_view.publish()
    content_view.read().version[0].promote(data={'environment_ids': lce.id})

    ak = module_target_sat.api.ActivationKey(
        content_view=content_view, organization=org.id, environment=lce.id
    ).create()

    # Edit capsule's taxonomies
    capsule = module_target_sat.cli.Capsule.update(
        {
            'name': module_capsule_configured.hostname,
            'organization-ids': org.id,
            'location-ids': loc.id,
        }
    )

    module_target_sat.cli.Capsule.content_add_lifecycle_environment(
        {
            'id': module_capsule_configured.nailgun_capsule.id,
            'organization-id': org.id,
            'lifecycle-environment': lce.name,
        }
    )

    return module_target_sat, org, lce, capsule, content_view, loc, ak


@pytest.mark.no_containers
@pytest.mark.rhel_ver_match('[789]')
def test_change_content_source(session, change_content_source_prep, rhel_contenthost):
    """
    This test exercises different ways to change host's content source

    :id: 5add68c3-16b1-496d-9b24-f5388013351d

    :expectedresults: Job invocation page should be correctly generated
        by the change content source action, generated script should also be correct

    :CaseComponent:Hosts-Content

    :Team: Phoenix-subscriptions
    """

    module_target_sat, org, lce, capsule, content_view, loc, ak = change_content_source_prep

    rhel_contenthost.register(org, loc, ak.name, module_target_sat)

    with module_target_sat.ui_session() as session:
        session.organization.select(org_name=org.name)
        session.location.select(loc_name=ANY_CONTEXT['location'])

        # STEP 1: Test the part where you use "Update hosts manually" button
        # Set the content source to the checked-out capsule
        # Check that generated script contains correct name of new content source
        rhel_contenthost_pre_values = rhel_contenthost.nailgun_host.content_facet_attributes
        generated_script = session.host.change_content_source_get_script(
            entities_list=[
                rhel_contenthost.hostname,
            ],
            content_source=capsule[0]['name'],
            lce=lce.name,
            content_view=content_view.name,
        )
        rhel_contenthost_post_values = rhel_contenthost.nailgun_host.content_facet_attributes
        content_source_from_script = re.search(r'--server.hostname=\"(.*?)\"', generated_script)

        assert content_source_from_script.group(1) == capsule[0]['name']
        assert rhel_contenthost_post_values['content_source']['name'] == capsule[0]['name']
        assert rhel_contenthost_post_values['content_view']['name'] == content_view.name
        assert rhel_contenthost_post_values['lifecycle_environment']['name'] == lce.name

        session.browser.refresh()

        # Step 2: Test the part where you use "Run job invocation" button
        # Change the rhel_contenthost's content source back to what it was before STEP 1
        # Check the prefilled job invocation page
        session.host.change_content_source(
            entities_list=[
                rhel_contenthost.hostname,
            ],
            content_source=rhel_contenthost_pre_values['content_source']['name'],
            lce=rhel_contenthost_pre_values['lifecycle_environment']['name'],
            content_view=rhel_contenthost_pre_values['content_view']['name'],
            run_job_invocation=True,
        )
        # Getting the data from the prefilled job invocation form
        selected_category_and_template = session.jobinvocation.get_job_category_and_template()
        selected_targeted_hosts = session.jobinvocation.get_targeted_hosts()

        assert selected_category_and_template['job_category'] == 'Katello'
        assert (
            selected_category_and_template['job_template']
            == 'Configure host for new content source'
        )
        assert selected_targeted_hosts['selected_hosts'] == [rhel_contenthost.hostname]

        session.jobinvocation.submit_prefilled_view()
        rhel_contenthost_post_values = rhel_contenthost.nailgun_host.content_facet_attributes
        assert (
            rhel_contenthost_post_values['content_source']['name']
            == rhel_contenthost_pre_values['content_source']['name']
        )
        assert (
            rhel_contenthost_post_values['content_view']['name']
            == rhel_contenthost_post_values['content_view']['name']
        )
        assert (
            rhel_contenthost_post_values['lifecycle_environment']['name']
            == rhel_contenthost_post_values['lifecycle_environment']['name']
        )


@pytest.mark.rhel_ver_match('8')
def test_positive_page_redirect_after_update(target_sat, current_sat_location):
    """Check that page redirects correctly after editing a host without making any changes.

    :id: 29c3397e-0010-11ef-bca4-000c2989e153

    :steps:
        1. Go to All Hosts page.
        2. Edit a host. Using the Sat. host is sufficient, no other host needs to be created or registered,
            because we need just a host with FQDN.
        3. Submit the host edit dialog without making any changes.

    :expectedresults: The page should be redirected to the host details page.

    :BZ: 2166303
    """
    client = target_sat
    with target_sat.ui_session() as session:
        session.location.select(loc_name=current_sat_location.name)
        session.host_new.update(client.hostname, {})

        assert 'page-not-found' not in session.browser.url
        assert client.hostname in session.browser.url


@pytest.mark.no_containers
@pytest.mark.rhel_ver_match([settings.content_host.default_rhel_version])
def test_host_status_honors_taxonomies(
    module_target_sat,
    test_name,
    rhel_contenthost,
    setup_content,
    default_location,
    default_org,
    default_org_lce,
):
    """Check that host status counts in Monitor -> Host Statuses show only hosts that the user has permissions to

    :id: 2c4e6df7-c17e-4074-b691-4d8e2efda062
    :steps:
        1. In a non-default organization, create a user
        2. As that user, check that host count is 0 in Monitor -> Host Statuses
        3. Add a host to the non-default org
        4. As that user, check that host count is 1 in Monitor -> Host Statuses

    :expectedresults: First, the user can't see any host, then they can see one host
    """
    ak, org, _ = setup_content

    lce = default_org_lce
    # Create content view environment for the default org
    content_view = module_target_sat.api.ContentView(organization=default_org).create()
    content_view.publish()
    published_cv = content_view.read()
    content_view_version = published_cv.version[0]
    content_view_version.promote(data={'environment_ids': lce.id})

    # default_org != org (== module_org)
    default_org_ak_name = gen_string('alpha')
    module_target_sat.cli_factory.make_activation_key(
        {
            'name': default_org_ak_name,
            'organization-id': default_org.id,
            'lifecycle-environment-id': lce.id,
            'content-view-id': published_cv.id,
        }
    )['name']
    # register the host to default_org
    assert (
        rhel_contenthost.register(
            default_org, default_location, default_org_ak_name, module_target_sat
        ).status
        == 0
    )
    host_id = module_target_sat.cli.Host.info({'name': rhel_contenthost.hostname})['id']
    password = gen_string('alpha')
    login = gen_string('alpha')
    # the user is in org
    module_target_sat.cli.User.create(
        {
            'organization-id': org.id,
            'location-id': default_location.id,
            'auth-source': 'Internal',
            'password': password,
            'mail': 'root@localhost',
            'login': login,
            'roles': ROLES,
        }
    )
    with module_target_sat.ui_session(test_name, user=login, password=password) as session:
        statuses = session.host.host_statuses()
    assert all(int(status['count'].split(': ')[1]) == 0 for status in statuses)
    # register the host to org
    assert rhel_contenthost.unregister().status == 0
    module_target_sat.cli.Host.delete({'id': host_id})
    assert rhel_contenthost.register(org, default_location, ak.name, module_target_sat).status == 0
    with module_target_sat.ui_session(test_name, user=login, password=password) as session:
        statuses = session.host.host_statuses()
    assert len([status for status in statuses if int(status['count'].split(': ')[1]) != 0]) == 1


@pytest.mark.parametrize(
    'module_repos_collection_with_setup',
    [
        {
            'distro': 'rhel8',
            'YumRepository': {'url': settings.repos.yum_3.url},
        }
    ],
    ids=['yum3'],
    indirect=True,
)
@pytest.mark.parametrize('finish_via', ['rex', 'custom_rex'])
@pytest.mark.parametrize(
    'package_management_action',
    [
        'install_1_pckg',
        'install_2_pckgs',
        'upgrade_1_pckg',
        'upgrade_all_pckgs',
        'remove_1_pckg',
        'remove_2_pckgs',
    ],
)
@pytest.mark.parametrize('number_of_hosts', [1, 2], ids=['1_host', '2_hosts'])
@pytest.mark.rhel_ver_list([settings.content_host.default_rhel_version])
@pytest.mark.no_containers
def test_positive_manage_packages(
    request,
    module_target_sat,
    mod_content_hosts,
    module_repos_collection_with_setup,
    new_host_ui,
    number_of_hosts,
    package_management_action,
    finish_via,
):
    """
    This test is testing the new Satellite feature - Managing packages on hosts via the new All hosts UI.
    It is highly parametrized so it can test various package management actions on various hosts.
    Test cases are defined by the combination of the following parameters:
    - number_of_hosts: 1 or 2
    - package_management_action: install_1_pckg, install_2_pckgs, upgrade_1_pckg, upgrade_all_pckgs, remove_1_pckg, remove_2_pckgs
    - finish_via: rex or custom_rex
    All this leads to 2 * 6 * 2 = 24 test cases in total.

    :id: 1d6760ca-9c7e-4267-9a4b-3f91d50c8eb1

    :steps:
        1. Setup hosts on Satellite, override reposets to enabled and refresh applicability so the package profile is updated
        2. Setup all the control flags for airgun entity
        3. Setup packages on the selected hosts so they can be managed in the next steps
        4. Run the selected package management action on the selected hosts
        5. Wait for the specific tasks to finish
        6. Assert the results

    :expectedresults: Various package management actions should run successfully on various hosts

    :CaseComponent: Hosts-Content

    :parametrized: yes

    :Team: Phoenix-subscriptions
    """

    packages = ['panda', 'seal']

    for host in mod_content_hosts:
        host.add_rex_key(module_target_sat)
        module_repos_collection_with_setup.setup_virtual_machine(host)

    product_name = module_repos_collection_with_setup.custom_product.name

    with module_target_sat.ui_session() as session:
        session.organization.select(module_repos_collection_with_setup.organization['name'])

        for host in mod_content_hosts:
            if (
                session.host_new.get_repo_sets(host.hostname, product_name)[0]['Status']
                == 'Disabled'
            ):
                session.host_new.override_repo_sets(
                    host.hostname, product_name, "Override to enabled"
                )
                session.host_new.refresh_applicability(host.hostname)
                latest_refresh_applicability_id = int(
                    module_target_sat.cli.JobInvocation().list()[0]['id']
                )
                module_target_sat.wait_for_tasks(
                    search_query=(
                        f'action: "Upload package profile for a host" and resource_id = {latest_refresh_applicability_id}'
                    )
                )

        # Define hosts to test based on the number of hosts
        hosts_to_test = []
        match number_of_hosts:
            case 1:
                hosts_to_test = [mod_content_hosts[0]]
            case 2:
                hosts_to_test = mod_content_hosts

        # Set default value to management action flags
        upgrade_all_packages_flag = upgrade_packages_flag = install_packages_flag = (
            remove_packages_flag
        ) = False

        # Set flags according to current parametrization
        match package_management_action:
            case 'install_1_pckg':
                install_packages_flag = True
                packages_to_install = [packages[0]]
                packages_to_upgrade = None
                packages_to_remove = None

            case 'install_2_pckgs':
                install_packages_flag = True
                packages_to_install = packages
                packages_to_upgrade = None
                packages_to_remove = None

            case 'upgrade_1_pckg':
                upgrade_packages_flag = True
                packages_to_install = None
                packages_to_upgrade = [packages[0]]
                packages_to_remove = None

            case 'upgrade_all_pckgs':
                upgrade_packages_flag = True
                upgrade_all_packages_flag = True
                packages_to_install = None
                packages_to_upgrade = packages
                packages_to_remove = None

            case 'remove_1_pckg':
                remove_packages_flag = True
                packages_to_install = None
                packages_to_upgrade = None
                packages_to_remove = [packages[0]]

            case 'remove_2_pckgs':
                remove_packages_flag = True
                packages_to_install = None
                packages_to_upgrade = None
                packages_to_remove = packages

        # Set flags based on current type of the finish
        match finish_via:
            case 'rex':
                manage_by_customized_rex_flag = False
            case 'custom_rex':
                manage_by_customized_rex_flag = True

        # Get the latest versions of wanted packages on the tested hosts
        tested_hosts_packages_latest_version_dicts = {}
        for host in hosts_to_test:
            # Check the latests versions of wanted packages
            result = host.run(f'dnf list {" ".join(packages)}').stdout
            # Cropping dnf output so it shows only packages
            packages_list = [line for line in result.split('\n')[3:-1]]
            packages_latest_version_dict = {}
            # Create dict containing {'package_name': 'version', ...} for further checks
            for item in packages_list:
                parts = item.split()
                # Remove architecture part from package name
                package_name = parts[0].split('.')[0]
                version = parts[1]  # parts look like ['package_name', 'version', 'repo']
                packages_latest_version_dict[package_name] = version

            tested_hosts_packages_latest_version_dicts[host.hostname] = (
                packages_latest_version_dict  # {'example.com':{'package_name': 'version', ...}, ...}
            )

        used_action = package_management_action.split('_')[0]

        if used_action == 'install':
            # Checking if wanted packages are available so they can be installed in the next step
            for host in hosts_to_test:
                assert host.run(f'rpm -q {" ".join(packages_to_install)}').status == len(
                    packages_to_install
                ), 'Some of the packages are already installed!'

        elif used_action == 'upgrade':
            # Installing and downgrading packages so they can be upgraded in the next step
            for host in hosts_to_test:
                assert (
                    host.run(
                        f'dnf list available | grep -E "{"|".join(packages_to_upgrade)}"'
                    ).status
                    == 0
                ), 'Wanted packages are not available!'
                assert host.run(f'dnf install {" ".join(packages_to_upgrade)} -y').status == 0, (
                    'Could not install wanted packages!'
                )
                assert host.run(f'dnf downgrade {" ".join(packages_to_upgrade)} -y').status == 0, (
                    'Packages were not downgraded!'
                )

        elif used_action == 'remove':
            # Installing packages so they can be removed in the next step
            for host in hosts_to_test:
                assert host.run(f'dnf install {" ".join(packages_to_remove)} -y').status == 0, (
                    'Could not install wanted packages!'
                )

        # Run airgun entity which performs Package management action based on the flags set above
        session.all_hosts.manage_packages(
            host_names=[host.hostname for host in hosts_to_test],
            upgrade_all_packages=upgrade_all_packages_flag,
            upgrade_packages=upgrade_packages_flag,
            install_packages=install_packages_flag,
            remove_packages=remove_packages_flag,
            packages_to_upgrade=packages_to_upgrade,
            packages_to_install=packages_to_install,
            packages_to_remove=packages_to_remove,
            manage_by_customized_rex=manage_by_customized_rex_flag,
        )

        # Wait till the job launched by the management action is finished
        job_id = int(module_target_sat.cli.JobInvocation().list()[0]['id'])
        if install_packages_flag:
            module_target_sat.wait_for_tasks(
                search_query=(
                    f'action: "Install package(s) name ^ ({",".join(packages_to_install)})" and resource_id = {job_id}'
                ),
            )

        elif upgrade_packages_flag and (not upgrade_all_packages_flag):
            module_target_sat.wait_for_tasks(
                f'action:  "Update package(s) name ^ ({",".join(packages_to_upgrade)})" and resource_id = {job_id}'
            )

        elif upgrade_all_packages_flag:
            if not manage_by_customized_rex_flag:
                module_target_sat.wait_for_tasks(
                    f'action: "Upgrade all packages" and resource_id = {job_id}'
                )
            else:
                module_target_sat.wait_for_tasks(
                    f'action: "Update package(s)" and resource_id = {job_id}'
                )

        elif remove_packages_flag:
            module_target_sat.wait_for_tasks(
                f'action: "Remove packages name ^ ({",".join(packages_to_remove)})" and resource_id = {job_id}'
            )

        # MAKE ASSERTS AFTER INSTALLING PACKAGES
        if used_action == 'install':
            for host in hosts_to_test:
                # Check that all the wanted packages are installed
                assert host.run(f'rpm -q {" ".join(packages_to_install)}').status == 0, (
                    'Some of the wanted packages is not installed!'
                )

                # Get versions of installed packages
                installed_packages = host.run(
                    f'rpm -qa {" ".join(packages_to_install)}'
                ).stdout.split('\n')[:-1]
                installed_packages_version_dict = {}
                # Create dict containing {'installed_package_name': 'version', ...} for further checks
                for package in installed_packages:
                    package_name, version = package.split('-')[0], '-'.join(package.split('-')[1:])
                    installed_packages_version_dict[package_name] = version[
                        : version.rfind('.')
                    ].strip()

                # Check that the latest version of packages is installed
                for package in packages_to_install:
                    assert (
                        installed_packages_version_dict[package]
                        == tested_hosts_packages_latest_version_dicts[host.hostname][package]
                    ), f'Package "{package}" is not installed in the latest version!'

        # MAKE ASSERTS AFTER UPGRADING PACKAGES
        elif used_action == 'upgrade':
            for host in hosts_to_test:
                # Get versions of installed packages
                installed_packages = host.run(
                    f'rpm -qa {" ".join(packages_to_upgrade)}'
                ).stdout.split('\n')[:-1]
                installed_packages_version_dict = {}
                # Create dict containing {'installed_package_name': 'version', ...} for further checks
                for package in installed_packages:
                    package_name, version = package.split('-')[0], '-'.join(package.split('-')[1:])
                    installed_packages_version_dict[package_name] = version[
                        : version.rfind('.')
                    ].strip()

                # Check that the package was upgraded to the latest version
                for package in packages_to_upgrade:
                    assert (
                        installed_packages_version_dict[package]
                        == tested_hosts_packages_latest_version_dicts[host.hostname][package]
                    ), f'Package "{package}" is not upgraded to the latest version!'

        # MAKE ASSERTS AFTER REMOVING PACKAGES
        elif used_action == 'remove':
            for host in hosts_to_test:
                # Assert that all the wanted packages were removed
                assert host.run(f'rpm -qa {" ".join(packages_to_remove)}').stdout == ''

    @request.addfinalizer
    def _cleanup():
        for host in hosts_to_test:
            time.sleep(5)
            assert host.run(f'dnf remove {" ".join(packages)} -y').status == 0, (
                'Could not remove installed packages in a finalizer!'
            )


@pytest.mark.parametrize('errata_to_install', ['1', '2'])
@pytest.mark.parametrize('manage_by_custom_rex', [True, False])
@pytest.mark.parametrize(
    'function_repos_collection_with_manifest',
    [
        {
            'distro': 'rhel8',
            'YumRepository': [
                {'url': settings.repos.yum_3.url},
                {'url': settings.repos.yum_1.url},
            ],
        }
    ],
    indirect=True,
)
@pytest.mark.no_containers
@pytest.mark.rhel_ver_match('8')
def test_all_hosts_manage_errata(
    session,
    module_target_sat,
    function_sca_manifest_org,
    content_hosts,
    function_repos_collection_with_manifest,
    manage_by_custom_rex,
    errata_to_install,
    new_host_ui,
):
    """Apply an errata on multiple hosts through bulk errata wizard in All Hosts page.

    :id: c14c87a3-fdeb-4ad2-af36-65aa17fc7d41

    :expectedresults: Errata can be bulk applied to hosts through the All Hosts page.

    :CaseComponent: Hosts-Content

    :Team: Phoenix-content
    """
    if errata_to_install == '1':
        errata_ids = settings.repos.yum_3.errata[25]
    if errata_to_install == '2':
        errata_ids = [settings.repos.yum_3.errata[25], settings.repos.yum_1.errata[1]]
    for host in content_hosts:
        host.add_rex_key(module_target_sat)
        function_repos_collection_with_manifest.setup_virtual_machine(
            host, enable_custom_repos=True
        )
        host.run(f'yum install -y {FAKE_7_CUSTOM_PACKAGE}')
        result = host.run(f'rpm -q {FAKE_7_CUSTOM_PACKAGE}')
        assert result.status == 0
        if errata_to_install == '2':
            host.run(f'yum install -y {FAKE_1_CUSTOM_PACKAGE}')
            result = host.run(f'rpm -q {FAKE_1_CUSTOM_PACKAGE}')
            assert result.status == 0
    with module_target_sat.ui_session() as session:
        session.organization.select(function_sca_manifest_org.name)
        session.location.select(loc_name=DEFAULT_LOC)
        session.all_hosts.manage_errata(
            host_names=[content_hosts[0].hostname, content_hosts[1].hostname],
            erratas_to_apply_by_id=errata_ids,
            manage_by_customized_rex=manage_by_custom_rex,
        )
        if errata_to_install == '2':
            errata_ids = f'{errata_ids[0]},{errata_ids[1]}'
        for host in content_hosts:
            task_result = module_target_sat.wait_for_tasks(
                search_query=(f'"Install errata errata_id ^ ({errata_ids}) on {host.hostname}"'),
                search_rate=2,
                max_tries=60,
            )
            task_status = module_target_sat.api.ForemanTask(id=task_result[0].id).poll()
            assert task_status['result'] == 'success'


def test_positive_manage_repository_sets(
    new_host_ui,
    module_target_sat,
    module_sca_manifest_org,
    module_lce,
    module_ak,
    rhel8_contenthost,
    rhel9_contenthost,
):
    """
    Change one or more repository status on multiple hosts through Manage content wizard

    :id: 4c9913d8-ce0d-4b50-901a-024aca207fc5

    :expectedresults: Repository status can be changed via All Hosts page > Manage content wizard.

    :CaseComponent: Hosts-Content

    :Team: Phoenix-content
    """
    content_hosts = [rhel8_contenthost, rhel9_contenthost]
    rhel_repos = ['rhel8_bos', 'rhel9_bos']
    all_repo_ids = []
    all_repo_names = []
    host_names = []
    status_to_be_changed = {
        0: 'Override to disabled',
        1: 'Override to enabled',
        2: 'Reset to default',
    }

    # Create content view
    content_view = module_target_sat.api.ContentView(organization=module_sca_manifest_org).create()
    content_view.repository = []

    # Enable rh repos and fetch repo ids
    for name in rhel_repos:
        rh_repo_id = module_target_sat.api_factory.enable_rhrepo_and_fetchid(
            basearch=DEFAULT_ARCHITECTURE,
            org_id=module_sca_manifest_org.id,
            product=REPOS[name]['product'],
            repo=REPOS[name]['name'],
            reposet=REPOS[name]['reposet'],
            releasever=REPOS[name]['releasever'],
        )
        all_repo_ids.append(rh_repo_id)

        # wait for repo creation/meta data generate task to complete
        module_target_sat.wait_for_tasks(
            search_query='Actions::Katello::Repository::MetadataGenerate',
            max_tries=5,
            search_rate=10,
        )

        # Read repository from repo id
        rh_repo = module_target_sat.api.Repository(id=rh_repo_id).read()

        # content view repositories
        content_view.repository.append(rh_repo)

    # Update content view repositories,publish and then promote content view to Library
    content_view = module_target_sat.api.ContentView(
        id=content_view.id, repository=content_view.repository
    ).update(['repository'])
    content_view.publish()
    content_view = content_view.read()
    cv_version = content_view.version[0]
    cv_version.promote(data={'environment_ids': module_lce.id})

    # Update activation key
    module_ak = module_target_sat.api.ActivationKey(
        id=module_ak.id,
        organization=module_sca_manifest_org,
        content_view=content_view,
        environment=module_lce,
    ).update()

    # register host to satellite and enable repository if those are disable
    for content_host in content_hosts:
        assert (
            content_host.register(
                module_sca_manifest_org, None, module_ak.name, module_target_sat
            ).status
            == 0
        )
        raw_output = content_host.execute('subscription-manager repos --list').stdout
        # Get repo name and add into empty list (this is workaround to avoid failure in airgun)
        data_list = raw_output.split('\n')
        for line in data_list:
            if "Repo Name" in line:
                repository = (line.split(':')[1]).lstrip()
                all_repo_names.append(repository)
        # If rhel repo is disabled then enable it
        if "Enabled:   0" in raw_output:
            rep_status = content_host.execute("subscription-manager repos --enable *").stdout
            assert "enabled for this system" in rep_status
        host_names.append(content_host.hostname)

    # Change one or more repository status on multiple hosts through Manage content wizard
    override_to_disabled = status_to_be_changed[0]
    with module_target_sat.ui_session() as session:
        session.organization.select(module_sca_manifest_org.name)
        session.all_hosts.manage_repository_sets(
            host_names=host_names,
            select_all_hosts=False,
            repository_names=all_repo_names,
            status_to_change=override_to_disabled,
        )
        # Check status of repositories on each host, it should be disabled.
        for content_host in content_hosts:
            output = content_host.execute('subscription-manager repos --list').stdout
            assert "Enabled:   0" in output, 'repository status not changed'

        # Now change one or more repository status to enable
        override_to_enabled = status_to_be_changed[1]
        session.all_hosts.manage_repository_sets(
            host_names=host_names,
            select_all_hosts=False,
            repository_names=all_repo_names,
            status_to_change=override_to_enabled,
        )

        # Check status of repositories on each host, it should be enabled.
        for content_host in content_hosts:
            output = content_host.execute('subscription-manager repos --list').stdout
            assert "Enabled:   1" in output, 'repository status not changed'


def test_disassociate_multiple_hosts(
    new_host_ui,
    request,
    target_sat,
    module_location,
    module_org,
    vmware,
    default_location,
):
    """
    Import multiple VMs from a VMware compute resource, disassociate them via the UI,
    and verify via API that their uuid and compute_resource_id are cleared.

    :id: e5af21c7-62ef-4cc7-a72a-ab6c26090b68

    :steps:
        1. Create all required entities (domain, subnet, hostgroup, etc.)
        2. Import 2 VMs from VMware into Satellite
        3. Disassociate the VMs via the All Hosts UI
        4. Verify via API that uuid and compute_resource_id are None

    :expectedresults: VMs are disassociated and their compute resource info is cleared.

    :CaseComponent: Hosts-Content

    :Team: Phoenix-subscriptions
    """

    cr_name = gen_string('alpha')

    # create entities for hostgroup
    target_sat.api.SmartProxy(
        id=target_sat.nailgun_smart_proxy.id, location=[default_location.id, module_location.id]
    ).update()
    domain = target_sat.api.Domain(
        organization=[module_org.id], location=[module_location]
    ).create()
    subnet = target_sat.api.Subnet(
        organization=[module_org.id], location=[module_location], domain=[domain]
    ).create()
    architecture = target_sat.api.Architecture().create()
    ptable = target_sat.api.PartitionTable(
        organization=[module_org.id], location=[module_location]
    ).create()
    operatingsystem = target_sat.api.OperatingSystem(
        architecture=[architecture], ptable=[ptable]
    ).create()
    medium = target_sat.api.Media(
        organization=[module_org.id], location=[module_location], operatingsystem=[operatingsystem]
    ).create()
    lce = (
        target_sat.api.LifecycleEnvironment(name="Library", organization=module_org.id)
        .search()[0]
        .read()
        .id
    )
    cv = target_sat.api.ContentView(organization=module_org).create()
    cv.publish()

    # create hostgroup
    hostgroup_name = gen_string('alpha')
    target_sat.api.HostGroup(
        name=hostgroup_name,
        architecture=architecture,
        domain=domain,
        subnet=subnet,
        location=[module_location.id],
        medium=medium,
        operatingsystem=operatingsystem,
        organization=[module_org],
        ptable=ptable,
        lifecycle_environment=lce,
        content_view=cv,
        content_source=target_sat.nailgun_smart_proxy.id,
    ).create()

    with target_sat.ui_session() as session:
        session.organization.select(org_name=module_org.name)
        session.location.select(loc_name=module_location.name)
        session.computeresource.create(
            {
                'name': cr_name,
                'provider': FOREMAN_PROVIDERS['vmware'],
                'provider_content.vcenter': vmware.hostname,
                'provider_content.user': settings.vmware.username,
                'provider_content.password': settings.vmware.password,
                'provider_content.datacenter.value': settings.vmware.datacenter,
                'locations.resources.assigned': [module_location.name],
                'organizations.resources.assigned': [module_org.name],
            }
        )
        session.hostgroup.update(
            hostgroup_name, {'host_group.deploy': f'{cr_name} ({FOREMAN_PROVIDERS["vmware"]})'}
        )

        cr_vm_names = [settings.vmware.vm_name, 'phoenix-testing-guest-rhel-8']
        vm_names_with_domains = [f'{name.replace(".", "")}.{domain.name}' for name in cr_vm_names]

        # Import VMs from VMware compute resource
        for cr_vm_name, vm_name_with_domain in zip(
            cr_vm_names, vm_names_with_domains, strict=False
        ):
            session.computeresource.vm_import(
                cr_name,
                cr_vm_name,
                hostgroup_name,
                module_location.name,
                name=cr_vm_name.replace('.', ''),
            )
            assert session.all_hosts.search(vm_name_with_domain)

        @request.addfinalizer
        def _cleanup():
            for vm_name in vm_names_with_domains:
                try:
                    target_sat.api.Host().search(query={"search": f'name={vm_name}'})[0].delete()
                except APIResponseError as e:
                    print(f"Failed to delete VM {vm_name}: {e}")

        for vm_name in vm_names_with_domains:
            # Get info about host from API
            host = target_sat.api.Host().search(query={"search": f'name={vm_name}'})[0]
            # Check that uuid and compute_resource_id are set
            assert host.uuid is not None, f"UUID for {vm_name} is not set"
            assert host.compute_resource.id is not None, (
                f"Compute resource ID for {vm_name} is not set"
            )

        session.all_hosts.disassociate_hosts(host_names=vm_names_with_domains)

        for vm_name in vm_names_with_domains:
            # Get info about host from API
            host = target_sat.api.Host().search(query={"search": f'name={vm_name}'})[0]
            # Check that uuid and compute_resource_id are set to None
            assert host.uuid is None, f"UUID for {vm_name} is not None after disassociation"
            assert host.compute_resource is None, (
                f"Compute resource ID for {vm_name} is not None after disassociation"
            )
