"""Unit tests for the ``report_templates`` paths.

:Requirement: Report templates

:CaseAutomation: Automated

:CaseComponent: Reporting

:team: Endeavour

:CaseImportance: High

"""

from datetime import UTC, datetime, timedelta
import re
import time

from fauxfactory import gen_string
import pytest
from requests import HTTPError
from wait_for import wait_for

from robottelo.config import settings
from robottelo.constants import (
    DEFAULT_ARCHITECTURE,
    FAKE_1_CUSTOM_PACKAGE,
    FAKE_1_CUSTOM_PACKAGE_NAME,
    FAKE_2_CUSTOM_PACKAGE,
    FAKE_9_YUM_OUTDATED_PACKAGES,
    PRDS,
    REPOS,
    REPOSET,
)
from robottelo.utils.datafactory import parametrized, valid_data_list

expected_report_columns = [
    'Name',
    'Global',
    'Build',
    'Compliance',
    'Configuration',
    'Errata',
    'Execution',
    'Insights',
    'Inventory',
    'RHEL lifecycle',
    'Traces',
]


@pytest.fixture(scope='module')
def setup_content(module_sca_manifest_org, module_target_sat):
    org = module_sca_manifest_org
    rh_repo_id = module_target_sat.api_factory.enable_rhrepo_and_fetchid(
        basearch='x86_64',
        org_id=org.id,
        product=PRDS['rhel'],
        repo=REPOS['rhst7']['name'],
        reposet=REPOSET['rhst7'],
        releasever=None,
    )
    rh_repo = module_target_sat.api.Repository(id=rh_repo_id).read()
    rh_repo.sync()
    custom_repo = module_target_sat.api.Repository(
        product=module_target_sat.api.Product(organization=org).create(),
    ).create()
    custom_repo.sync()
    lce = module_target_sat.api.LifecycleEnvironment(organization=org).create()
    cv = module_target_sat.api.ContentView(
        organization=org,
        repository=[rh_repo_id, custom_repo.id],
    ).create()
    cv.publish()
    cvv = cv.read().version[0].read()
    cvv.promote(data={'environment_ids': lce.id, 'force': False})
    ak = module_target_sat.api.ActivationKey(
        content_view=cv, max_hosts=100, organization=org, environment=lce, auto_attach=True
    ).create()
    all_content = ak.product_content(data={'content_access_mode_all': '1'})['results']
    content_label = [repo['label'] for repo in all_content if repo['name'] == custom_repo.name][0]
    ak.content_override(
        data={'content_overrides': [{'content_label': content_label, 'value': '1'}]}
    )
    return ak, org


# Tests for ``katello/api/v2/report_templates``.


@pytest.mark.parametrize('name', **parametrized(valid_data_list()))
def test_positive_CRUDL(name, target_sat):
    """Create, Read, Update, Delete, List

    :id: a2a577db-144e-4761-a42e-e83885464786

    :parametrized: yes

    :setup: User with reporting access rights

    :steps:

        1. Create Report Template
        2. List Report Templates, verify it's there
        3. Read Report Template
        4. Update Report Template, read again
        5. Delete Report template, check it's not present

    :expectedresults: All operations succeed, no template present in the end

    :CaseImportance: Critical
    """
    # Create
    template1 = gen_string('alpha')
    rt = target_sat.api.ReportTemplate(name=name, template=template1).create()
    # List
    res = target_sat.api.ReportTemplate().search(query={'search': f'name="{name}"'})
    assert name in list(map(lambda x: x.name, res))
    # Read
    rt = target_sat.api.ReportTemplate(id=rt.id).read()
    assert name == rt.name
    assert template1 == rt.template
    # Update
    template2 = gen_string('alpha')
    target_sat.api.ReportTemplate(id=rt.id, template=template2).update(['template'])
    rt = target_sat.api.ReportTemplate(id=rt.id).read()
    assert template2 == rt.template
    # Delete
    target_sat.api.ReportTemplate(id=rt.id).delete()
    with pytest.raises(HTTPError):
        rt = target_sat.api.ReportTemplate(id=rt.id).read()


def test_positive_generate_report_nofilter(target_sat):
    """Generate Host - Statuses report

    :id: a4b687db-144e-4761-a42e-e93887464986

    :setup: User with reporting access rights, some report template, at least two hosts

    :steps:

        1. POST /api/report_templates/:id/generate

    :expectedresults: Report is generated for all hosts visible to user

    :CaseImportance: Critical
    """
    host_name = gen_string('alpha').lower()
    target_sat.api.Host(name=host_name).create()
    rt = (
        target_sat.api.ReportTemplate().search(query={'search': 'name="Host - Statuses"'})[0].read()
    )
    res = rt.generate()
    for column_name in expected_report_columns:
        assert column_name in res
    assert host_name in res


def test_positive_generate_report_filter(target_sat):
    """Generate Host - Statuses report

    :id: a4b677cb-144e-4761-a42e-e93887464986

    :setup: User with reporting access rights, some report template, at least two hosts

    :steps:

        1. POST /api/report_templates/:id/generate ... # define input_values

    :expectedresults: Report is generated (only) for the host specified by the filter

    :CaseImportance: High
    """
    host1_name = gen_string('alpha').lower()
    host2_name = gen_string('alpha').lower()
    target_sat.api.Host(name=host1_name).create()
    target_sat.api.Host(name=host2_name).create()
    rt = (
        target_sat.api.ReportTemplate().search(query={'search': 'name="Host - Statuses"'})[0].read()
    )
    res = rt.generate(data={"input_values": {"hosts": host2_name}})
    for column_name in expected_report_columns:
        assert column_name in res
    assert host1_name not in res
    assert host2_name in res


def test_positive_report_add_userinput(target_sat):
    """Add user input to template, use it in template, generate template

    :id: a4a577db-144e-4761-a42e-e86887464986

    :setup: User with reporting access rights

    :steps:

        1. PUT /api/templates/:template_id/template_inputs/:id ... # add user input

    :expectedresults: User input is assigned to the report template and used in template

    :CaseImportance: High
    """
    host_name = gen_string('alpha').lower()
    input_name = gen_string('alpha').lower()
    input_value = gen_string('alpha').lower()
    template_name = gen_string('alpha').lower()
    template = f'<%= "value=\\"" %><%= input(\'{input_name}\') %><%= "\\"" %>'
    target_sat.api.Host(name=host_name).create()
    rt = target_sat.api.ReportTemplate(name=template_name, template=template).create()
    target_sat.api.TemplateInput(
        name=input_name,
        input_type="user",
        template=rt.id,
    ).create()
    ti = target_sat.api.TemplateInput(template=rt.id).search()[0].read()
    assert input_name == ti.name
    res = rt.generate(data={"input_values": {input_name: input_value}})
    assert f'value="{input_value}"' in res


def test_positive_lock_clone_nodelete_unlock_report(target_sat):
    """Lock report template. Check it can be cloned and can't be deleted or edited.
       Unlock. Check it can be deleted and edited.

    :id: a4c577db-144e-4761-a42e-e83887464986

    :setup: User with reporting access rights, some report template that is not locked

    :steps:

        1. Create template
        2. Lock template
        3. Clone template, check cloned data
        4. Try to delete template
        5. Try to edit template
        6. Unlock template
        7. Edit template
        8. Delete template

    :expectedresults: Report is locked

    :CaseImportance: High

    :BZ: 1680458
    """
    # 1. Create template
    template_name = gen_string('alpha').lower()
    template_clone_name = gen_string('alpha').lower()
    template1 = gen_string('alpha')
    template2 = gen_string('alpha')
    rt = target_sat.api.ReportTemplate(name=template_name, template=template1).create()
    # 2. Lock template
    target_sat.api.ReportTemplate(id=rt.id, locked=True).update(["locked"])
    rt = rt.read()
    assert rt.locked is True
    # 3. Clone template, check cloned data
    rt.clone(data={'name': template_clone_name})
    cloned_rt = (
        target_sat.api.ReportTemplate()
        .search(query={'search': f'name="{template_clone_name}"'})[0]
        .read()
    )
    assert template_clone_name == cloned_rt.name
    assert template1 == cloned_rt.template
    # 4. Try to delete template
    with pytest.raises(HTTPError):
        rt.delete()
    # In BZ1680458, exception is thrown but template is deleted anyway
    assert (
        len(target_sat.api.ReportTemplate().search(query={'search': f'name="{template_name}"'}))
        != 0
    )
    # 5. Try to edit template
    with pytest.raises(HTTPError):
        target_sat.api.ReportTemplate(id=rt.id, template=template2).update(["template"])
    rt = rt.read()
    assert template1 == rt.template
    # 6. Unlock template
    target_sat.api.ReportTemplate(id=rt.id, locked=False).update(["locked"])
    rt = rt.read()
    assert rt.locked is False
    # 7. Edit template
    target_sat.api.ReportTemplate(id=rt.id, template=template2).update(["template"])
    rt = rt.read()
    assert template2 == rt.template
    # 8. Delete template
    rt.delete()
    assert (
        len(target_sat.api.ReportTemplate().search(query={'search': f'name="{template_name}"'}))
        == 0
    )


@pytest.mark.stubbed
def test_positive_export_report():
    """Export report template

    :id: a4b577db-144e-4761-a42e-a83887464986

    :setup: User with reporting access rights, some report template

    :steps:

        1. /api/report_templates/:id/export

    :expectedresults: Report script is shown

    :CaseImportance: High
    """


@pytest.mark.stubbed
def test_positive_generate_report_sanitized():
    """Generate report template where there are values in comma outputted which might
    break CSV format

    :id: a4b577db-144e-4961-a42e-e93887464986

    :setup: User with reporting access rights, Host Statuses report,
            a host with OS that has comma in its name

    :steps:

        1. POST /api/report_templates/:id/generate

    :expectedresults: Report is generated in proper CSV format (value with comma is quoted)

    :CaseImportance: Medium
    """


def test_negative_create_report_without_name(module_target_sat):
    """Try to create a report template with empty name

    :id: a4b577db-144e-4771-a42e-e93887464986

    :setup: User with reporting access rights

    :steps:

        1. POST /api/report_templates

    :expectedresults: Report is not created

    :CaseImportance: Medium
    """
    with pytest.raises(HTTPError) as report_response:
        module_target_sat.api.ReportTemplate(name=' ', template=gen_string('alpha')).create()
    assert "Name can't be blank" in report_response.value.response.text


@pytest.mark.rhel_ver_match('N-2')
@pytest.mark.no_containers
def test_positive_applied_errata(
    rhel_contenthost, target_sat, function_location, function_org, function_lce
):
    """Generate an Applied Errata report

    :id: a4b577db-141e-4871-a42e-e93887464986

    :setup: A Host with some applied errata.

    :steps:

        1. Generate an Applied Errata report

    :expectedresults: A report is generated with all applied errata listed

    :CaseImportance: Medium
    """

    ERRATUM_ID = str(settings.repos.yum_6.errata[2])
    created_vals = target_sat.cli_factory.setup_org_for_a_custom_repo(
        {
            'url': settings.repos.yum_9.url,
            'organization-id': function_org.id,
            'lifecycle-environment-id': function_lce.id,
        }
    )
    activation_key = target_sat.api.ActivationKey(id=created_vals['activationkey-id']).read()
    result = rhel_contenthost.register(
        function_org, function_location, activation_key.name, target_sat
    )
    assert f'The registered system name is: {rhel_contenthost.hostname}' in result.stdout
    assert rhel_contenthost.subscribed
    rhel_contenthost.execute(r'subscription-manager repos --enable \*')
    assert rhel_contenthost.execute(f'yum install -y {FAKE_1_CUSTOM_PACKAGE}').status == 0
    assert rhel_contenthost.execute(f'rpm -q {FAKE_1_CUSTOM_PACKAGE}').status == 0
    task_id = target_sat.api.JobInvocation().run(
        data={
            'feature': 'katello_errata_install',
            'inputs': {'errata': ERRATUM_ID},
            'targeting_type': 'static_query',
            'search_query': f'name = {rhel_contenthost.hostname}',
            'organization_id': function_org.id,
        },
    )['id']
    target_sat.wait_for_tasks(
        search_query=(f'label = Actions::RemoteExecution::RunHostsJob and id = {task_id}'),
        search_rate=15,
        max_tries=10,
    )
    rt = (
        target_sat.api.ReportTemplate()
        .search(query={'search': 'name="Host - Applied Errata"'})[0]
        .read()
    )
    res = rt.generate(
        data={
            'organization_id': function_org.id,
            'report_format': 'json',
            'input_values': {
                'Filter Errata Type': 'all',
                'Include Last Reboot': 'no',
                'Status': 'all',
            },
        }
    )
    assert res[0]['erratum_id'] == ERRATUM_ID
    assert res[0]['issued']


@pytest.mark.rhel_ver_match('N-2')
@pytest.mark.no_containers
def test_positive_applied_errata_report_with_invalid_errata(
    rhel_contenthost,
    target_sat,
    function_location,
    function_org,
    function_lce,
):
    """Generate an Applied Errata report after an invalid errata has been applied

    :id: cf64f193-870d-4053-ae4b-28148424b2e2

    :setup: A Host with some invalid applied errata.

    :steps:

        1. Apply invalid errata
        2. Generate an Applied Errata report

    :expectedresults: A report is generated without failures

    :BZ: 2176368

    :customerscenario: true
    """

    created_vals = target_sat.cli_factory.setup_org_for_a_custom_repo(
        {
            'url': settings.repos.yum_6.url,
            'organization-id': function_org.id,
            'lifecycle-environment-id': function_lce.id,
        }
    )
    activation_key = target_sat.api.ActivationKey(id=created_vals['activationkey-id']).read()

    result = rhel_contenthost.register(
        function_org, function_location, activation_key.name, target_sat
    )
    assert f'The registered system name is: {rhel_contenthost.hostname}' in result.stdout
    assert rhel_contenthost.subscribed
    rhel_contenthost.execute(r'subscription-manager repos --enable \*')
    assert rhel_contenthost.execute(f'yum install -y {FAKE_1_CUSTOM_PACKAGE}').status == 0
    assert rhel_contenthost.execute(f'rpm -q {FAKE_1_CUSTOM_PACKAGE}').status == 0
    task_id = target_sat.api.JobInvocation().run(
        data={
            'feature': 'katello_errata_install',
            'inputs': {'errata': 'invalid-errata'},
            'targeting_type': 'static_query',
            'search_query': f'name = {rhel_contenthost.hostname}',
            'organization_id': function_org.id,
        },
    )['id']
    target_sat.wait_for_tasks(
        search_query=(f'label = Actions::RemoteExecution::RunHostsJob and id = {task_id}'),
        search_rate=15,
        max_tries=10,
    )
    rt = (
        target_sat.api.ReportTemplate()
        .search(query={'search': 'name="Host - Applied Errata"'})[0]
        .read()
    )
    rt.generate(
        data={
            'organization_id': function_org.id,
            'report_format': 'json',
            'input_values': {
                'Filter Errata Type': 'all',
                'Include Last Reboot': 'no',
                'Status': 'all',
            },
        }
    )


@pytest.mark.rhel_ver_match('N-2')
@pytest.mark.no_containers
def test_positive_applied_errata_by_search(
    rhel_contenthost, target_sat, function_org, function_lce
):
    """Generate an Applied Errata report

    :id: 0f7d2772-47a4-4215-b555-dd8ee675372f

    :setup: A Host with some applied errata.

    :steps:

        1. Generate an Applied Errata report

    :expectedresults: A report is generated with all applied errata listed

    :CaseImportance: Medium
    """

    ERRATUM_ID = str(settings.repos.yum_6.errata[2])
    created_vals = target_sat.cli_factory.setup_org_for_a_custom_repo(
        {
            'url': settings.repos.yum_6.url,
            'organization-id': function_org.id,
            'lifecycle-environment-id': function_lce.id,
        }
    )
    activation_key = target_sat.api.ActivationKey(id=created_vals['activationkey-id']).read()
    errata_name = (
        target_sat.api.Errata()
        .search(query={'search': f'errata_id="{ERRATUM_ID}"'})[0]
        .read()
        .description
    )
    result = rhel_contenthost.register(function_org, None, activation_key.name, target_sat)
    assert f'The registered system name is: {rhel_contenthost.hostname}' in result.stdout
    assert rhel_contenthost.subscribed
    rhel_contenthost.execute(r'subscription-manager repos --enable \*')
    assert rhel_contenthost.execute(f'yum install -y {FAKE_1_CUSTOM_PACKAGE}').status == 0
    assert rhel_contenthost.execute(f'rpm -q {FAKE_1_CUSTOM_PACKAGE}').status == 0
    # sleep added to reduce flakiness of the test
    rhel_contenthost.execute('subscription-manager repos | sleep 10')
    task_id = target_sat.api.JobInvocation().run(
        data={
            'feature': 'katello_errata_install_by_search',
            'inputs': {'Errata search query': errata_name},
            'targeting_type': 'static_query',
            'search_query': f'name = {rhel_contenthost.hostname}',
            'organization_id': function_org.id,
        },
    )['id']
    target_sat.wait_for_tasks(
        search_query=(f'label = Actions::RemoteExecution::RunHostsJob and id = {task_id}'),
        search_rate=20,
        poll_timeout=2500,
    )
    rt = (
        target_sat.api.ReportTemplate()
        .search(query={'search': 'name="Host - Applied Errata"'})[0]
        .read()
    )
    res = rt.generate(
        data={
            'organization_id': function_org.id,
            'report_format': 'json',
            'input_values': {
                'Filter Errata Type': 'all',
                'Include Last Reboot': 'no',
                'Status': 'all',
            },
        }
    )
    assert res[0]['erratum_id'] == ERRATUM_ID
    assert res[0]['issued']


@pytest.mark.no_containers
@pytest.mark.rhel_ver_match('N-2')
def test_positive_applied_errata_for_specific_hosts(
    mod_content_hosts,
    module_target_sat,
    module_org,
    module_lce,
):
    """Generate an Applied Errata report by hostname, with unique erratum
    applied to multiple hosts.

    :id: 57025661-37cb-44bd-917a-a173605926ad

    :setup: Two registered hosts, each with a different applicable erratum.

    :steps:
        1. Apply errata by empty search " " to each host.
        2. Generate the Hosts Applied Errata report for both hosts.

    :expectedresults:
        1. Only a single errata is applied to each host, expected package updated.
        2. Two reports are generated, one for each host.
        3. Only the hostname specified is listed in the generated report.
        4. In each report, only the single errata_id applied for that host is listed.

    :CaseImportance: High

    :customerscenario: true

    :Verifies: SAT-30611

    """
    RHSA = {
        'host': mod_content_hosts[0],
        'errata_id': settings.repos.yum_9.errata[0],  # RHSA-2012:0055
        'outdated_pkg': FAKE_9_YUM_OUTDATED_PACKAGES[6],  # walrus-0.71-1.noarch
    }
    RHBA = {
        'host': mod_content_hosts[1],
        'errata_id': settings.repos.yum_9.errata[-1],  # RHBA-2012:1030
        'outdated_pkg': FAKE_9_YUM_OUTDATED_PACKAGES[7],  # kangaroo-0.1-1.noarch
    }
    setup = module_target_sat.cli_factory.setup_org_for_a_custom_repo(
        {
            'url': settings.repos.yum_9.url,
            'organization-id': module_org.id,
            'lifecycle-environment-id': module_lce.id,
        }
    )
    activation_key = module_target_sat.api.ActivationKey(id=setup['activationkey-id']).read()
    # register both hosts and install their outdated package
    for host_info in [RHSA, RHBA]:
        chost = host_info['host']
        result = chost.register(module_org, None, activation_key.name, module_target_sat)
        assert f'The registered system name is: {chost.hostname}' in result.stdout
        assert chost.subscribed
        assert chost.execute(f'yum install -y {host_info["outdated_pkg"]}').status == 0

    # now each erratum is applicable to one host,
    # Katello: errata install by search, check each result
    for host_info in [RHSA, RHBA]:
        chost = host_info['host']
        assert chost.applicable_errata_count == 1
        assert chost.applicable_package_count == 1
        # apply by empty search, " " (Select All), and passing the hostname
        job_invoc = module_target_sat.api.JobInvocation().run(
            data={
                'feature': 'katello_errata_install_by_search',
                'inputs': {'Errata search query': " "},
                'targeting_type': 'static_query',
                'search_query': f'name = {chost.hostname}',
                'organization_id': module_org.id,
            },
            timeout=2500,
        )
        module_target_sat.wait_for_tasks(
            search_query=(
                f'label = Actions::RemoteExecution::RunHostsJob and id = {job_invoc["id"]}'
            ),
            search_rate=20,
            poll_timeout=120,
        )
        job_invoc = module_target_sat.api.ForemanTask(id=job_invoc['id']).poll()  # Host(s) job
        remote_action = module_target_sat.api.ForemanTask().search(  # install subtask
            query={'search': f'action ~ "Install errata on {chost.hostname}"'}
        )
        assert chost.execute('subscription-manager refresh').status == 0
        assert chost.applicable_errata_count == 0
        assert chost.applicable_package_count == 0
        # job yielded only a single task for one host, success
        assert job_invoc['result'] == 'success'
        assert job_invoc['output']['host_count'] == 1
        assert job_invoc['output']['total_count'] == 1
        assert job_invoc['output']['planned_count'] == 1
        assert job_invoc['output']['success_count'] == 1
        assert job_invoc['output']['failed_count'] == 0
        # we only expect one sub-task, applied one errata to one host,
        # updated the single outdated package
        assert len(remote_action) == 1
        remote_action = remote_action[0].poll()
        assert remote_action['humanized']['action'] == 'Remote action:'
        assert chost.hostname == remote_action['input']['host']['name']
        assert host_info['outdated_pkg'] in remote_action['humanized']['output']

    # after both applied to respective host,
    # generate Hosts - Applied Errata report by hostname for both hosts
    gen_reports = []
    for host_info in [RHSA, RHBA]:
        chost = host_info['host']
        report_data = {
            'organization_id': module_org.id,
            'report_format': 'json',
            'input_values': {
                'Hosts filter': chost.hostname,
                'Filter Errata Type': 'all',
                'Include Last Reboot': 'no',
                'Status': 'all',
            },
        }
        report = (
            module_target_sat.api.ReportTemplate()
            .search(query={'search': 'name="Host - Applied Errata"'})[0]
            .read()
            .generate(data=report_data)
        )
        gen_reports.append(report)

    # RHSA host's report has RHSA errata, and not RHBA
    rhsa_report_errata = [errata['erratum_id'] for errata in gen_reports[0]]
    assert RHSA['errata_id'] in rhsa_report_errata, (
        f'Expected errata_id: "{RHSA["errata_id"]}" in generated report, but got:\n{gen_reports[0]}'
    )
    assert RHBA['errata_id'] not in rhsa_report_errata
    # RHSA host's report has expected hostname, and not the other hostname
    rhsa_report_hosts = [errata['hostname'] for errata in gen_reports[0]]
    assert RHSA['host'].hostname in rhsa_report_hosts
    assert RHBA['host'].hostname not in rhsa_report_hosts

    # RHBA host's report has RHBA errata, and not RHSA
    rhba_report_errata = [errata['erratum_id'] for errata in gen_reports[1]]
    assert RHBA['errata_id'] in rhba_report_errata, (
        f'Expected errata_id: "{RHBA["errata_id"]}" in generated report, but got:\n{gen_reports[1]}'
    )
    assert RHSA['errata_id'] not in rhba_report_errata
    # RHBA host's report has expected hostname, and not the other hostname
    rhba_report_hosts = [errata['hostname'] for errata in gen_reports[1]]
    assert RHBA['host'].hostname in rhba_report_hosts
    assert RHSA['host'].hostname not in rhba_report_hosts


@pytest.mark.stubbed
def test_positive_generate_nonblocking():
    """Generate an Applied Errata report

    :id: a4b577db-142e-4871-a42e-e93887464986

    :setup: User with reporting access rights, some host with applied errata

    :steps:

        1. POST /api/report_templates/:id/schedule_report
        2. GET /api/report_templates/:id/report_data/:job_id

    :expectedresults: A report is generated asynchronously

    :CaseImportance: Medium
    """


@pytest.mark.stubbed
def test_positive_generate_email_compressed():
    """Generate an Applied Errata report, get it by e-mail, compressed

    :id: a4b577db-143e-4871-a42e-e93887464986

    :setup: User with reporting access rights, some host with applied errata

    :steps:

        1. POST /api/report_templates/:id/schedule_report

    :expectedresults: A report is generated asynchronously, the result
                      is compressed and mailed to the specified address

    :CaseImportance: Medium
    """


@pytest.mark.stubbed
def test_positive_generate_email_uncompressed():
    """Generate an Applied Errata report, get it by e-mail, uncompressed

    :id: a4b577db-143f-4871-a42e-e93887464986

    :setup: User with reporting access rights, some host with applied errata

    :steps:

        1. POST /api/report_templates/:id/schedule_report

    :expectedresults: A report is generated asynchronously, the result
                      is not compressed and is mailed
                      to the specified address

    :CaseImportance: Medium
    """


@pytest.mark.stubbed
def test_negative_bad_email():
    """Report can't be generated when incorrectly formed mail specified

    :id: a4b577db-164e-4871-a42e-e93887464986

    :setup: User with reporting access rights, some host with applied errata

    :steps:

        1. POST /api/report_templates/:id/schedule_report

    :expectedresults: Error message about wrong e-mail address, no task is triggered

    :CaseImportance: Medium
    """


@pytest.mark.stubbed
def test_positive_cleanup_task_running():
    """Report can't be generated when incorrectly formed mail specified

    :id: a4b577db-145e-4871-a42e-e93887464986

    :setup: Installed Satellite, user that can list running tasks

    :steps:

        1. List running tasks

    :expectedresults: Report cleanup task is running

    :CaseImportance: Medium
    """


@pytest.mark.stubbed
def test_negative_nonauthor_of_report_cant_download_it():
    """The resulting report should only be downloadable by
       the user that generated it or admin. Check.

    :id: a4b577db-146e-4871-a42e-e93887464986

    :setup: Installed Satellite, user that can list running tasks

    :steps:

        1. POST /api/report_templates/:id/schedule_report
        2. GET /api/report_templates/:id/report_data/:job_id (as a different non-admin user)

    :expectedresults: Report can't be downloaded. Error.

    :CaseImportance: Medium
    """


@pytest.mark.no_containers
def test_positive_generate_job_report(setup_content, module_target_sat, content_hosts):
    """Generate a report using the Job - Invocation Report template.

    :id: 946c39db-3061-43d7-b922-1be61f0c7d93

    :BZ: 1761012

    :steps:
        1. Register a host and properly setup REX for it.
        2. Run a simple job with predictable output
        3. Using the Job ID, generate a report using the Job - Invocation
           report template.

    :expectedresults: Report returns correct information (Hostname is set correctly,
        the output is what would be expected.)

    :customerscenario: true
    """
    ak, org = setup_content
    for host in content_hosts:
        host.register(org, None, ak.name, module_target_sat)
        host.add_rex_key(module_target_sat)
        assert host.subscribed
        # Run a Job on the Host
    template_id = (
        module_target_sat.api.JobTemplate()
        .search(query={'search': 'name="Run Command - Script Default"'})[0]
        .id
    )
    job = module_target_sat.api.JobInvocation().run(
        synchronous=False,
        data={
            'job_template_id': template_id,
            'inputs': {
                'command': 'pwd',
            },
            'targeting_type': 'static_query',
            'search_query': f'name ^ ({content_hosts[0].hostname} && {content_hosts[1].hostname}',
        },
    )
    module_target_sat.wait_for_tasks(f'resource_type = JobInvocation and resource_id = {job["id"]}')
    result = module_target_sat.api.JobInvocation(id=job['id']).read()
    assert result.succeeded == 2
    rt = (
        module_target_sat.api.ReportTemplate()
        .search(query={'search': 'name="Job - Invocation Report"'})[0]
        .read()
    )
    res = rt.generate(
        data={
            'organization_id': org.id,
            'report_format': "json",
            'input_values': {"job_id": job["id"]},
        }
    )
    assert {i['Host'] for i in res} == {i.hostname for i in content_hosts}
    assert '/root' in res[0]['stdout']
    assert '/root' in res[1]['stdout']


@pytest.mark.no_containers
@pytest.mark.rhel_ver_match('N-2')
def test_positive_installable_errata(
    target_sat, function_org, function_lce, function_activation_key, rhel_contenthost
):
    """Generate an Installable Errata report using the Report Template - Available Errata,
        with the option of 'Installable'.

    :id: 6263a0fa-5021-4553-939b-84fb71c81d59

    :setup: A Host with some applied errata

    :steps:
        1. Install an outdated package version
        2. Apply some errata which updates the package
        3. Downgrade the package impacted by the erratum
        4. Perform a search for any Available Errata
        5. Generate an Installable Report from the Available Errata

    :expectedresults: A report is generated with the installable errata listed

    :CaseImportance: Medium

    :customerscenario: true

    :BZ: 1726504
    """
    custom_cv = target_sat.api.ContentView(organization=function_org).create()
    ERRATUM_ID = str(settings.repos.yum_6.errata[2])
    target_sat.cli_factory.setup_org_for_a_custom_repo(
        {
            'url': settings.repos.yum_6.url,
            'organization-id': function_org.id,
            'content-view-id': custom_cv.id,
            'lifecycle-environment-id': function_lce.id,
            'activationkey-id': function_activation_key.id,
        }
    )
    result = rhel_contenthost.register(
        activation_keys=function_activation_key.name,
        org=function_org,
        target=target_sat,
        loc=None,
    )
    assert f'The registered system name is: {rhel_contenthost.hostname}' in result.stdout
    assert rhel_contenthost.subscribed

    # Remove package if already installed on this host
    rhel_contenthost.execute(f'yum remove -y {FAKE_1_CUSTOM_PACKAGE_NAME}')
    # Install the outdated package version
    rhel_contenthost.execute(r'subscription-manager repos --enable \*')
    assert rhel_contenthost.execute(f'yum install -y {FAKE_1_CUSTOM_PACKAGE}').status == 0
    assert (
        rhel_contenthost.execute(f'rpm -q {FAKE_1_CUSTOM_PACKAGE_NAME}').stdout.strip()
        == FAKE_1_CUSTOM_PACKAGE
    )

    # Install/Apply the errata
    task_id = target_sat.api.JobInvocation().run(
        data={
            'feature': 'katello_errata_install',
            'inputs': {'errata': ERRATUM_ID},
            'targeting_type': 'static_query',
            'search_query': f'name = {rhel_contenthost.hostname}',
            'organization_id': function_org.id,
        },
    )['id']
    target_sat.wait_for_tasks(
        search_query=(f'label = Actions::RemoteExecution::RunHostsJob and id = {task_id}'),
        search_rate=15,
        max_tries=10,
    )
    # Check that applying erratum updated the package
    assert (
        rhel_contenthost.execute(f'rpm -q {FAKE_1_CUSTOM_PACKAGE_NAME}').stdout.strip()
        == FAKE_2_CUSTOM_PACKAGE
    )
    # Downgrade the package
    assert rhel_contenthost.execute(f'yum downgrade -y {FAKE_1_CUSTOM_PACKAGE}').status == 0

    # Data to generate Installable Errata report
    _rt_input_data = {
        'organization_id': function_org.id,
        'report_format': "json",
        'input_values': {
            'Installability': 'installable',
        },
    }

    # Gather Errata using the template 'Available Errata', may take some time
    # When condition is met, newest Report Template will have Errata entries
    wait_for(
        lambda: (
            target_sat.api.ReportTemplate()
            .search(query={'search': 'name="Host - Available Errata"'})[0]
            .read()
            .generate(data=_rt_input_data)
            != []
        ),
        timeout=120,
        delay=10,
    )
    report = (
        target_sat.api.ReportTemplate()
        .search(query={'search': 'name="Host - Available Errata"'})[0]
        .read()
        .generate(data=_rt_input_data)
    )
    assert report
    installable_errata = report[0]
    assert FAKE_1_CUSTOM_PACKAGE_NAME in installable_errata['Packages']
    assert installable_errata['Erratum'] == ERRATUM_ID


@pytest.mark.rhel_ver_match('[^6]')
def test_positive_installed_products(
    target_sat,
    rhel_contenthost,
    default_location,
    function_sca_manifest_org,
):
    """Generate 'Host - Installed Products' report for an SCA host.

    :id: d290daa2-aaba-4f4d-8eee-d8a540415320

    :parametrized: yes

    :setup:
        1. RH content published in a CV, promoted to LCE, AK created.
           All inside an SCA-enabled organization.
        2. A RHEL content host.

    :steps:
        1. Set syspurpose tags of the content host via subman.
        2. Register the content host using the AK.
        3. Generate 'Host - Installed Products' report.
        4. Verify the report generated from the template.

    :expectedresults:
        1. Report is generated with correct values.

    :CaseImportance: Medium
    """
    org = function_sca_manifest_org
    lce_name = gen_string('alpha')
    cv_name = gen_string('alpha')
    sys_tags = {'role': gen_string('alpha'), 'usage': gen_string('alpha')}

    for key, val in sys_tags.items():
        assert rhel_contenthost.execute(f'subscription-manager {key} --set {val}').status == 0, (
            f'Setting of {key} failed.'
        )

    rh_repo = {
        'basearch': DEFAULT_ARCHITECTURE,
        'product': REPOS['rhae2']['product'],
        'name': REPOS['rhae2']['name'],
        'reposet': REPOS['rhae2']['reposet'],
        'releasever': None,
    }
    repo_id = target_sat.api_factory.enable_sync_redhat_repo(rh_repo, org.id)
    cv = target_sat.api_factory.cv_publish_promote(cv_name, lce_name, repo_id, org.id)
    ak = target_sat.api.ActivationKey(
        content_view=cv, organization=org, environment=cv.environment[-1]
    ).create()

    rhel_contenthost.register(org, default_location, ak.name, target_sat)
    assert rhel_contenthost.subscribed, 'Host registration failed.'

    input_data = {
        'organization_id': org.id,
        'report_format': "json",
        'input_values': {
            'hosts': rhel_contenthost.hostname,
        },
    }
    report = (
        target_sat.api.ReportTemplate()
        .search(query={'search': 'name="Host - Installed Products"'})[0]
        .read()
        .generate(data=input_data)
    )

    assert report, 'No report generated.'
    assert report[0]['Host Name'] == rhel_contenthost.hostname, 'Incorrect host was reported.'
    assert report[0]['Organization'] == org.name, 'Incorrect org was reported.'
    assert report[0]['Content View Environments'] == f'{lce_name}/{cv_name}', (
        'Incorrect content view environment(s) reported.'
    )
    assert report[0]['Role'] == sys_tags['role'], 'Incorrect role was reported.'
    assert report[0]['Usage'] == sys_tags['usage'], 'Incorrect usage was reported.'

    # Get the installed products via rake and compare them with generated report
    rake = target_sat.execute(
        f'echo "Host.find_by(name: \'{rhel_contenthost.hostname}\').'
        'subscription_facet.installed_products" | foreman-rake console'
    )
    assert rake.status == 0, f'Rake call failed with this output:\n({rake.stdout}).'

    pattern = re.compile(r'name: "(.*?)"\s*.*?\s*cp_product_id: "(.*?)"')
    matches = pattern.findall(rake.stdout)
    products = [f'{match[0]} ({match[1]})' for match in matches]
    assert len(products), 'No installed products to compare.'

    assert set(products) == set(report[0]['Products']), 'Reported products do not match.'


@pytest.mark.no_containers
@pytest.mark.rhel_ver_match('N-2')
def test_positive_applied_errata_by_install_date(
    module_rhel_contenthost,
    module_target_sat,
    module_org,
    module_lce,
):
    """Generate two Applied Errata reports, for Today and Yesterday,
        specifying the SINCE and UP-TO date fields, when the erratum
        were installed (UTC for CI testing).

    :id: 33f5abfd-16dd-4f2e-a9c2-c1ce3aaa33d6

    :setup:
        1. A registered host with outdated applicable packages installed.
        2. Apply the applicable erratum (all of FAKE_9_YUM).

    :steps:
        1. Generate an Applied Errata report for 'Today' (Since: 5 minutes prior)
        2. Generate an Applied Errata report for 'Yesterday' (Up to: 24 hours prior)

    :expectedresults:
        1. Today's report is generated with all applied erratum listed that were installed today.
        2. Yesterday's report is generated and is empty, as no erratum were installed prior.

    :CaseImportance: Medium

    """
    ERRATUM_IDS = [str(errata) for errata in settings.repos.yum_9.errata]
    setup = module_target_sat.cli_factory.setup_org_for_a_custom_repo(
        {
            'url': settings.repos.yum_9.url,
            'organization-id': module_org.id,
            'lifecycle-environment-id': module_lce.id,
        }
    )
    activation_key = module_target_sat.api.ActivationKey(id=setup['activationkey-id']).read()
    result = module_rhel_contenthost.register(
        module_org, None, activation_key.name, module_target_sat
    )
    assert f'The registered system name is: {module_rhel_contenthost.hostname}' in result.stdout
    assert module_rhel_contenthost.subscribed
    module_rhel_contenthost.execute(r'subscription-manager repos --enable \*')
    # Install all FAKE_9_YUM outdated pkgs
    assert (
        module_rhel_contenthost.execute(
            f'yum install -y {" ".join(FAKE_9_YUM_OUTDATED_PACKAGES)}'
        ).status
        == 0
    )
    assert module_rhel_contenthost.execute('subscription-manager refresh').status == 0
    assert module_rhel_contenthost.applicable_errata_count == len(ERRATUM_IDS)
    # sleep added to reduce flakiness of the test
    time.sleep(10)
    # 'Since' time for today (UTC): set to 5 minutes prior to installs below
    today_utc = (datetime.now(UTC) - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    # Apply all FAKE_9_YUM erratum
    for _id in ERRATUM_IDS:
        task_id = module_target_sat.api.JobInvocation().run(
            data={
                'feature': 'katello_errata_install',
                'inputs': {'errata': _id},
                'targeting_type': 'static_query',
                'search_query': f'name = {module_rhel_contenthost.hostname}',
                'organization_id': module_org.id,
            },
        )['id']
        module_target_sat.wait_for_tasks(
            search_query=(f'label = Actions::RemoteExecution::RunHostsJob and id = {task_id}'),
            search_rate=20,
            poll_timeout=2500,
        )
    assert module_rhel_contenthost.execute('subscription-manager refresh').status == 0
    assert module_rhel_contenthost.applicable_errata_count == 0
    rt = (
        module_target_sat.api.ReportTemplate()
        .search(query={'search': 'name="Host - Applied Errata"'})[0]
        .read()
    )
    # Generate a report for Today and Yesterday (UTC)
    report_today = rt.generate(
        data={
            'organization_id': module_org.id,
            'report_format': 'json',
            'input_values': {
                'Since': today_utc,
                'Filter Errata Type': 'all',
                'Include Last Reboot': 'no',
                'Status': 'all',
            },
        }
    )
    assert len(report_today) == len(ERRATUM_IDS)
    # Today's report: all ERRATUM_IDS are contained within
    assert all(
        errata_id in [entry['erratum_id'] for entry in report_today] for errata_id in ERRATUM_IDS
    )
    # Yesterday's report is empty
    yesterday_utc = (datetime.now(UTC) - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    report_yesterday = rt.generate(
        data={
            'organization_id': module_org.id,
            'report_format': 'json',
            'input_values': {
                'Up to': yesterday_utc,
                'Filter Errata Type': 'all',
                'Include Last Reboot': 'no',
                'Status': 'all',
            },
        }
    )
    assert len(report_yesterday) == 0
