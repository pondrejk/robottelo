"""Unit tests for the ``organizations`` paths.

Each class tests a single URL. A full list of URLs to be tested can be found on your satellite:
http://<satellite-host>/apidoc/v2/organizations.html

:Requirement: Organization

:CaseAutomation: Automated

:CaseComponent: OrganizationsandLocations

:Team: Endeavour

:CaseImportance: High

"""

import http
import json
from random import randint

from fauxfactory import gen_string
from nailgun import client
import pytest
from requests.exceptions import HTTPError

from robottelo.config import get_credentials
from robottelo.constants import DEFAULT_ORG
from robottelo.utils.datafactory import (
    filtered_datapoint,
    invalid_values_list,
    parametrized,
)
from robottelo.utils.issue_handlers import is_open


@filtered_datapoint
def valid_org_data_list():
    """List of valid data for input testing.

    Note: The maximum allowed length of org name is 242 only. This is an
    intended behavior (Also note that 255 is the standard across other
    entities)
    """
    return dict(
        alpha=gen_string('alpha', randint(1, 242)),
        numeric=gen_string('numeric', randint(1, 242)),
        alphanumeric=gen_string('alphanumeric', randint(1, 242)),
        latin1=gen_string('latin1', randint(1, 242)),
        utf8=gen_string('utf8', randint(1, 85)),
        cjk=gen_string('cjk', randint(1, 85)),
        html=gen_string('html', randint(1, 85)),
    )


class TestOrganization:
    """Tests for the ``organizations`` path."""

    def test_positive_create(self, target_sat):
        """Create an organization using a 'text/plain' content-type.

        :id: 6f67a3f0-0c1d-498c-9a35-28207b0faec2

        :expectedresults: HTTP 415 is returned.

        :CaseImportance: Critical
        """
        organization = target_sat.api.Organization()
        organization.create_missing()
        response = client.post(
            organization.path(),
            organization.create_payload(),
            auth=get_credentials(),
            headers={'content-type': 'text/plain'},
            verify=False,
        )
        if is_open('SAT-20559'):
            assert response.status_code in [http.client.UNSUPPORTED_MEDIA_TYPE, 500]
        else:
            assert response.status_code == http.client.UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.build_sanity
    @pytest.mark.parametrize('name', **parametrized(valid_org_data_list()))
    def test_positive_create_with_name_and_description(self, name, target_sat):
        """Create an organization and provide a name and description.

        :id: afeea84b-61ca-40bf-bb16-476432919115

        :expectedresults: The organization has the provided attributes and an
            auto-generated label.

        :CaseImportance: Critical

        :parametrized: yes
        """
        org = target_sat.api.Organization(name=name, description=name).create()
        assert org.name == name
        assert org.description == name

        # Was a label auto-generated?
        assert hasattr(org, 'label')
        assert isinstance(org.label, str)
        assert len(org.label) > 0

    @pytest.mark.parametrize('name', **parametrized(invalid_values_list()))
    def test_negative_create_with_invalid_name(self, name, target_sat):
        """Create an org with an incorrect name.

        :id: 9c6a4b45-a98a-4d76-9865-92d992fa1a22

        :expectedresults: The organization cannot be created.

        :parametrized: yes
        """
        with pytest.raises(HTTPError):
            target_sat.api.Organization(name=name).create()

    def test_negative_create_with_same_name(self, target_sat):
        """Create two organizations with identical names.

        :id: a0f5333c-cc83-403c-9bf7-08fb372909dc

        :expectedresults: The second organization cannot be created.

        :CaseImportance: Critical
        """
        name = target_sat.api.Organization().create().name
        with pytest.raises(HTTPError):
            target_sat.api.Organization(name=name).create()

    def test_negative_check_org_endpoint(self, module_sca_manifest_org):
        """Check manifest cert is not exposed in api endpoint

        :id: 24130e54-cd7a-41de-ac78-6e89aebabe30

        :expectedresults: no cert information in org api endpoint

        :customerscenario: true

        :bz: 1828549

        :CaseImportance: High
        """
        orgstring = json.dumps(module_sca_manifest_org.read_json())
        assert 'BEGIN CERTIFICATE' not in orgstring
        assert 'BEGIN RSA PRIVATE KEY' not in orgstring

    def test_positive_search(self, target_sat):
        """Create an organization, then search for it by name.

        :id: f6f1d839-21f2-4676-8683-9f899cbdec4c

        :expectedresults: Searching returns at least one result.

        :CaseImportance: High
        """
        org = target_sat.api.Organization().create()
        orgs = target_sat.api.Organization().search(query={'search': f'name="{org.name}"'})
        assert len(orgs) == 1
        assert orgs[0].id == org.id
        assert orgs[0].name == org.name

    def test_negative_create_with_wrong_path(self, target_sat):
        """Attempt to create an organization using foreman API path
        (``api/v2/organizations``)

        :id: 499ae5ef-b1e4-4fb8-967a-57d525e06326

        :BZ: 1241068

        :expectedresults: API returns 404 error with 'Route overridden by
            Katello' message

        :CaseImportance: Critical
        """
        org = target_sat.api.Organization()
        org._meta['api_path'] = 'api/v2/organizations'
        with pytest.raises(HTTPError) as err:
            org.create()
        assert err.value.response.status_code == 404
        assert 'Route overridden by Katello' in err.value.response.text

    def test_default_org_id_check(self, target_sat):
        """test to check the default_organization id

        :id: df066396-a069-4e9e-b3c1-c6d34a755ec0

        :BZ: 1713269

        :expectedresults: The default_organization ID remain 1.

        :CaseImportance: Low
        """
        default_org_id = (
            target_sat.api.Organization().search(query={'search': f'name="{DEFAULT_ORG}"'})[0].id
        )
        assert default_org_id == 1


class TestOrganizationUpdate:
    """Tests for the ``organizations`` path."""

    @pytest.fixture
    def module_org(self, target_sat):
        """Create an organization."""
        return target_sat.api.Organization().create()

    @pytest.mark.parametrize('name', **parametrized(valid_org_data_list()))
    def test_positive_update_name(self, module_org, name):
        """Update an organization's name with valid values.

        :id: 68f2ba13-2538-407c-9f33-2447fca28cd5

        :expectedresults: The organization's name is updated.

        :CaseImportance: High

        :parametrized: yes
        """
        module_org.name = name
        module_org = module_org.update(['name'])
        assert module_org.name == name

    @pytest.mark.parametrize('desc', **parametrized(valid_org_data_list()))
    def test_positive_update_description(self, module_org, desc):
        """Update an organization's description with valid values.

        :id: bd223197-1021-467e-8714-c1a767ae89af

        :expectedresults: The organization's description is updated.

        :CaseImportance: Medium

        :parametrized: yes
        """
        module_org.description = desc
        module_org = module_org.update(['description'])
        assert module_org.description == desc

    def test_positive_update_user(self, module_org, target_sat):
        """Update an organization, associate user with it.

        :id: 2c0c0061-5b4e-4007-9f54-b61d6e65ef58

        :expectedresults: User is associated with organization.

        """
        user = target_sat.api.User().create()
        module_org.user = [user]
        module_org = module_org.update(['user'])
        assert len(module_org.user) == 1
        assert module_org.user[0].id == user.id

    def test_positive_update_subnet(self, module_org, target_sat):
        """Update an organization, associate subnet with it.

        :id: 3aa0b9cb-37f7-4e7e-a6ec-c1b407225e54

        :expectedresults: Subnet is associated with organization.

        """
        subnet = target_sat.api.Subnet().create()
        module_org.subnet = [subnet]
        module_org = module_org.update(['subnet'])
        assert len(module_org.subnet) == 1
        assert module_org.subnet[0].id == subnet.id

    def test_positive_add_and_remove_hostgroup(self, target_sat):
        """Add a hostgroup to an organization and then remove it

        :id: 7eb1aca7-fd7b-404f-ab18-21be5052a11f

        :BZ: 1395229

        :expectedresults: Hostgroup is added to organization and then removed

        :CaseImportance: Medium
        """
        org = target_sat.api.Organization().create()
        hostgroup = target_sat.api.HostGroup().create()
        org.hostgroup = [hostgroup]
        org = org.update(['hostgroup'])
        assert len(org.hostgroup) == 1
        org.hostgroup = []
        org = org.update(['hostgroup'])
        assert len(org.hostgroup) == 0

    @pytest.mark.upgrade
    def test_positive_add_and_remove_smart_proxy(self, target_sat):
        """Add a smart proxy to an organization

        :id: e21de720-3fa2-429b-bd8e-b6a48a13146d

        :expectedresults: Smart proxy is successfully added to organization

        :BZ: 1395229

        """
        # Every Satellite has a built-in smart proxy, so let's find it
        smart_proxy = target_sat.api.SmartProxy().search(
            query={'search': f'url = {target_sat.url}:9090'}
        )
        # Check that proxy is found and unpack it from the list
        assert len(smart_proxy) > 0
        smart_proxy = smart_proxy[0]
        # By default, newly created organization uses built-in smart proxy,
        # so we need to remove it first
        org = target_sat.api.Organization().create()
        org.smart_proxy = []
        org = org.update(['smart_proxy'])
        # Verify smart proxy was actually removed
        assert len(org.smart_proxy) == 0

        # Add smart proxy to organization
        org.smart_proxy = [smart_proxy]
        org = org.update(['smart_proxy'])
        # Verify smart proxy was actually added
        assert len(org.smart_proxy) == 1
        assert org.smart_proxy[0].id == smart_proxy.id

        org.smart_proxy = []
        org = org.update(['smart_proxy'])
        # Verify smart proxy was actually removed
        assert len(org.smart_proxy) == 0

    @pytest.mark.parametrize('update_field', ['name', 'label'])
    def test_negative_update(self, module_org, update_field, target_sat):
        """Update an organization's attributes with invalid values.

        :id: b7152d0b-5ab0-4d68-bfdf-f3eabcb5fbc6

        :expectedresults: The organization's attributes are not updated.

        :CaseImportance: Critical

        :parametrized: yes

        :BZ: 1089996

        :CaseImportance: Medium
        """
        update_dict = {
            update_field: gen_string(str_type='utf8', length=256 if update_field == 'name' else 10)
        }
        with pytest.raises(HTTPError):
            target_sat.api.Organization(id=module_org.id, **update_dict).update([update_field])
