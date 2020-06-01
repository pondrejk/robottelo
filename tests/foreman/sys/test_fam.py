"""Test class foreman ansible modules

:Requirement: Other

:CaseAutomation: Automated

:CaseLevel: System

:TestType: Functional

:CaseImportance: Medium

:Upstream: No
"""
from robottelo import ssh
from robottelo.constants import FOREMAN_ANSIBLE_MODULES
from robottelo.decorators import destructive
from robottelo.decorators import run_in_one_thread


@destructive
@run_in_one_thread
def test_positive_ansible_modules():
    """Foreman ansible modules installation test

    :CaseComponent: Ansible

    :id: 553a927e-2665-4227-8542-0258d7b1ccc4

    :expectedresults: ansible-collection-redhat-satellite package is
        available and supported modules are contained

    """
    result = ssh.command(
        'yum install -y ansible-collection-redhat-satellite --disableplugin=foreman-protector'
    )
    assert result.return_code == 0
    for module_name in FOREMAN_ANSIBLE_MODULES:
        result = ssh.command(f'ansible-doc redhat.satellite.{module_name} -s')
        assert result.return_code == 0
        doc_name = result.stdout[1].lstrip()[:-1]
        assert doc_name == module_name
