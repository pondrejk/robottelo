"""CLI tests for logging.

:Requirement: Logging

:CaseAutomation: Automated

:CaseComponent: Logging

:Team: Endeavour

:CaseImportance: Medium

"""

import re

from fauxfactory import gen_string
import pytest

from robottelo.config import settings
from robottelo.logging import logger

pytestmark = pytest.mark.e2e


def cut_lines(start_line, end_line, source_file, out_file, host):
    """Given start and end line numbers, cut lines from source file
    and put them in out file."""
    return host.execute(
        f'sed -n "{start_line},{end_line} p" {source_file} < {source_file} > {out_file}'
    )


def test_positive_logging_from_foreman_core(target_sat):
    """Check that GET command to Hosts API is logged and has request ID.

    :id: 0785260d-cb81-4351-a7cb-d7841335e2de

    :expectedresults: line of log with GET has request ID

    :CaseImportance: Medium
    """

    GET_line_found = False
    source_log = '/var/log/foreman/production.log'
    test_logfile = '/var/tmp/logfile_from_foreman_core'
    # get the number of lines in the source log before the test
    line_count_start = target_sat.execute(f'wc -l < {source_log}').stdout.strip('\n')
    # hammer command for this test
    result = target_sat.execute('hammer host list')
    assert result.status == 0, f'Non-zero status for host list: {result.stderr}'
    # get the number of lines in the source log after the test
    line_count_end = target_sat.execute(f'wc -l < {source_log}').stdout.strip('\n')
    # get the log lines of interest, put them in test_logfile
    cut_lines(line_count_start, line_count_end, source_log, test_logfile, target_sat)
    # use same location on remote and local for log file extract
    target_sat.get(remote_path=test_logfile)
    # search the log file extract for the line with GET to host API
    with open(test_logfile) as logfile:
        for line in logfile:
            if re.search(r'Started GET \"\/api/hosts\?page=1', line):
                logger.info('Found the line with GET to hosts API')
                GET_line_found = True
                # Confirm the request ID was logged in the line with GET
                match = re.search(r'\[I\|app\|\w{8}\]', line)
                assert match, "Request ID not found"
                logger.info("Request ID found for logging from foreman core")
                break
    assert GET_line_found, "The GET command to list hosts was not found in logs."


def test_positive_logging_from_foreman_proxy(target_sat):
    """Check PUT to Smart Proxy API to refresh the features is logged and has request ID.

    :id: 0ecd8406-6cf1-4520-b8b6-8a164a1e60c2

    :expectedresults: line of log with PUT has request ID

    :CaseImportance: Medium
    """

    PUT_line_found = False
    request_id = None
    source_log_1 = '/var/log/foreman/production.log'
    test_logfile_1 = '/var/tmp/logfile_1_from_proxy'
    source_log_2 = '/var/log/foreman-proxy/proxy.log'
    test_logfile_2 = '/var/tmp/logfile_2_from_proxy'
    # get the number of lines in the source logs before the test
    line_count_start_1 = target_sat.execute(f'wc -l < {source_log_1}').stdout.strip('\n')
    line_count_start_2 = target_sat.execute(f'wc -l < {source_log_2}').stdout.strip('\n')
    # hammer command for this test
    result = target_sat.execute('hammer proxy refresh-features --id 1')
    assert result.status == 0, f'Non-zero status for host list: {result.stderr}'
    # get the number of lines in the source logs after the test
    line_count_end_1 = target_sat.execute(f'wc -l < {source_log_1}').stdout.strip('\n')
    line_count_end_2 = target_sat.execute(f'wc -l < {source_log_2}').stdout.strip('\n')
    # get the log lines of interest, put them in test_logfile_1
    cut_lines(line_count_start_1, line_count_end_1, source_log_1, test_logfile_1, target_sat)
    # get the log lines of interest, put them in test_logfile_2
    cut_lines(line_count_start_2, line_count_end_2, source_log_2, test_logfile_2, target_sat)
    # use same location on remote and local for log file extract
    target_sat.get(remote_path=test_logfile_1)
    # use same location on remote and local for log file extract
    target_sat.get(remote_path=test_logfile_2)
    # search the log file extract for the line with PUT to host API
    with open(test_logfile_1) as logfile:
        for line in logfile:
            if re.search(r'Started PUT \"\/api\/smart_proxies\/1\/refresh', line):
                logger.info('Found the line with PUT to foreman proxy API')
                PUT_line_found = True
                # Confirm the request ID was logged in the line with PUT
                match = re.search(r'\[I\|app\|\w{8}\]', line)
                assert match, "Request ID not found"
                logger.info("Request ID found for logging from foreman proxy")
                p = re.compile(r"\w{8}")
                result = p.search(line)
                request_id = result.group(0)
                break
    assert PUT_line_found, "The PUT command to refresh proxies was not found in logs."
    # search the local copy of proxy.log file for the same request ID
    with open(test_logfile_2) as logfile:
        for line in logfile:
            # Confirm request ID was logged in proxy.log
            match = line.find(request_id)
            assert match, "Request ID not found in proxy.log"
            logger.info("Request ID also found in proxy.log")
            break


def test_positive_logging_from_candlepin(module_org, module_sca_manifest, target_sat):
    """Check logging after manifest upload.

    :id: 8c06e501-52d7-4baf-903e-7de9caffb066

    :expectedresults: line of logs with POST has request ID

    :CaseImportance: Medium
    """

    POST_line_found = False
    source_log = '/var/log/candlepin/candlepin.log'
    test_logfile = '/var/tmp/logfile_from_candlepin'
    # regex for a version 4 UUID (8-4-4-12 format)
    regex = r"\b[0-9a-f]{8}\b-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-\b[0-9a-f]{12}\b"
    # get the number of lines in the source log before the test
    line_count_start = target_sat.execute(f'wc -l < {source_log}').stdout.strip('\n')
    # command for this test
    with module_sca_manifest as manifest:
        target_sat.upload_manifest(module_org.id, manifest, interface='CLI')
    # get the number of lines in the source log after the test
    line_count_end = target_sat.execute(f'wc -l < {source_log}').stdout.strip('\n')
    # get the log lines of interest, put them in test_logfile
    cut_lines(line_count_start, line_count_end, source_log, test_logfile, target_sat)
    # use same location on remote and local for log file extract
    target_sat.get(remote_path=test_logfile)
    # search the log file extract for the line with POST to candlepin API
    with open(test_logfile) as logfile:
        for line in logfile:
            if re.search(r'verb=POST, uri=/candlepin/owners/{0}', line.format(module_org.name)):
                logger.info('Found the line with POST to candlepin API')
                POST_line_found = True
                # Confirm the request ID was logged in the line with POST
                match = re.search(regex, line)
                assert match, "Request ID not found"
                logger.info("Request ID found for logging from candlepin")
                break
    assert POST_line_found, "The POST command to candlepin was not found in logs."


def test_positive_logging_from_dynflow(module_org, target_sat):
    """Check POST to repositories API is logged while enabling a repo \
        and it has the request ID.

    :id: 2d1a5f64-0b1c-4f95-ad20-881134717c4c

    :expectedresults: line of log with POST has request ID

    :CaseImportance: Medium
    """

    POST_line_found = False
    source_log = '/var/log/foreman/production.log'
    test_logfile = '/var/tmp/logfile_dynflow'
    product = target_sat.api.Product(organization=module_org).create()
    repo_name = gen_string('alpha')
    # get the number of lines in the source log before the test
    line_count_start = target_sat.execute(f'wc -l < {source_log}').stdout.strip('\n')
    # command for this test
    new_repo = target_sat.api.Repository(name=repo_name, product=product).create()
    logger.info(f'Created Repo {new_repo.name} for dynflow log test')
    # get the number of lines in the source log after the test
    line_count_end = target_sat.execute(f'wc -l < {source_log}').stdout.strip('\n')
    # get the log lines of interest, put them in test_logfile
    cut_lines(line_count_start, line_count_end, source_log, test_logfile, target_sat)
    # use same location on remote and local for log file extract
    target_sat.get(remote_path=test_logfile)
    # search the log file extract for the line with POST to to repositories API
    with open(test_logfile) as logfile:
        for line in logfile:
            if re.search(r'Started POST \"/katello\/api\/v2\/repositories', line):
                logger.info('Found the line with POST to repositories API.')
                POST_line_found = True
                # Confirm the request ID was logged in the line with POST
                match = re.search(r'\[I\|app\|\w{8}\]', line)
                assert match, "Request ID not found"
                logger.info("Request ID found for logging from dynflow ")
    assert POST_line_found, "The POST command to enable a repo was not found in logs."


def test_positive_logging_from_pulp3(module_org, target_sat):
    """
    Verify Pulp3 logs are getting captured using pulp3 correlation ID

    :id: 8d5718e6-3442-47d6-b541-0aa78d007e8b

    :CaseImportance: High
    """
    source_log = '/var/log/foreman/production.log'
    test_logfile = '/var/log/messages'

    # Create custom product and repository
    product_name = gen_string('alpha')
    name = product_name
    label = product_name
    desc = product_name
    product = target_sat.cli_factory.make_product(
        {'description': desc, 'label': label, 'name': name, 'organization-id': module_org.id},
    )
    repo = target_sat.cli_factory.make_repository(
        {
            'organization-id': module_org.id,
            'product-id': product['id'],
            'url': settings.repos.yum_0.url,
        },
    )
    # Synchronize the repository
    target_sat.cli.Product.synchronize({'id': product['id'], 'organization-id': module_org.id})
    target_sat.cli.Repository.synchronize({'id': repo['id']})
    # Get the id of repository sync from task
    task_out = target_sat.execute(
        "hammer task list | grep -F 'Synchronize repository {\"text\"=>\"repository'"
    ).stdout.splitlines()[0][:8]
    prod_log_out = target_sat.execute(f'grep  {task_out} {source_log}').stdout.splitlines()[0]
    # Get correlation id of pulp from production logs
    pulp_correlation_id = re.search(r'\[I\|bac\|\w{8}\]', prod_log_out).group()[7:15]
    # verify pulp correlation id in message
    message_log = target_sat.execute(f'cat {test_logfile} | grep {pulp_correlation_id}')
    assert message_log.status == 0
