"""Unit tests for the ``activation_keys`` paths.

:Requirement: Activationkey

:CaseAutomation: Automated

:CaseComponent: ActivationKeys

:team: Phoenix-subscriptions

:CaseImportance: High


"""

import http

from fauxfactory import gen_integer, gen_string
from nailgun import client
import pytest
from requests.exceptions import HTTPError

from robottelo.config import get_credentials, user_nailgun_config
from robottelo.constants import PRDS, REPOS, REPOSET
from robottelo.utils.datafactory import (
    filtered_datapoint,
    invalid_names_list,
    parametrized,
    valid_data_list,
)


@filtered_datapoint
def _good_max_hosts():
    """Return a list of valid ``max_hosts`` values."""
    return [gen_integer(*limits) for limits in ((1, 20), (10000, 20000))]


@filtered_datapoint
def _bad_max_hosts():
    """Return a list of invalid ``max_hosts`` values."""
    return [gen_integer(-100, -1), 0, gen_string('alpha')]


def test_positive_create_unlimited_hosts(target_sat):
    """Create a plain vanilla activation key.

    :id: 1d73b8cc-a754-4637-8bae-d9d2aaf89003

    :expectedresults: Check that activation key is created and its
        "unlimited_hosts" attribute defaults to true.

    :CaseImportance: Critical
    """
    assert target_sat.api.ActivationKey().create().unlimited_hosts is True


@pytest.mark.parametrize('max_host', **parametrized(_good_max_hosts()))
def test_positive_create_limited_hosts(max_host, target_sat):
    """Create an activation key with limited hosts.

    :id: 9bbba620-fd98-4139-a44b-af8ce330c7a4

    :expectedresults: Check that activation key is created and that hosts
        number is limited

    :CaseImportance: Critical

    :parametrized: yes
    """
    act_key = target_sat.api.ActivationKey(max_hosts=max_host, unlimited_hosts=False).create()
    assert act_key.max_hosts == max_host
    assert act_key.unlimited_hosts is False


@pytest.mark.parametrize('key_name', **parametrized(valid_data_list()))
def test_positive_create_with_name(key_name, target_sat):
    """Create an activation key providing the initial name.

    :id: 749e0d28-640e-41e5-89d6-b92411ce73a3

    :expectedresults: Activation key is created and contains provided name.

    :CaseImportance: Critical

    :parametrized: yes
    """
    act_key = target_sat.api.ActivationKey(name=key_name).create()
    assert key_name == act_key.name


@pytest.mark.parametrize('desc', **parametrized(valid_data_list()))
def test_positive_create_with_description(desc, target_sat):
    """Create an activation key and provide a description.

    :id: 64d93726-6f96-4a2e-ab29-eb5bfa2ff8ff

    :expectedresults: Created entity contains the provided description.

    :parametrized: yes
    """
    act_key = target_sat.api.ActivationKey(description=desc).create()
    assert desc == act_key.description


def test_negative_create_with_no_host_limit(target_sat):
    """Create activation key without providing limitation for hosts number

    :id: a9e756e1-886d-4f0d-b685-36ce4247517d

    :expectedresults: Activation key is not created

    :CaseImportance: Critical
    """
    with pytest.raises(HTTPError):
        target_sat.api.ActivationKey(unlimited_hosts=False).create()


@pytest.mark.parametrize('max_host', **parametrized(_bad_max_hosts()))
def test_negative_create_with_invalid_host_limit(max_host, target_sat):
    """Create activation key with invalid limit values for hosts number.

    :id: c018b177-2074-4f1a-a7e0-9f38d6c9a1a6

    :expectedresults: Activation key is not created

    :CaseImportance: Low

    :parametrized: yes
    """
    with pytest.raises(HTTPError):
        target_sat.api.ActivationKey(max_hosts=max_host, unlimited_hosts=False).create()


@pytest.mark.parametrize('name', **parametrized(invalid_names_list()))
def test_negative_create_with_invalid_name(name, target_sat):
    """Create activation key providing an invalid name.

    :id: 5f7051be-0320-4d37-9085-6904025ad909

    :expectedresults: Activation key is not created

    :CaseImportance: Low

    :parametrized: yes
    """
    with pytest.raises(HTTPError):
        target_sat.api.ActivationKey(name=name).create()


@pytest.mark.parametrize('max_host', **parametrized(_good_max_hosts()))
def test_positive_update_limited_host(max_host, target_sat):
    """Create activation key then update it to limited hosts.

    :id: 34ca8303-8135-4694-9cf7-b20f8b4b0a1e

    :expectedresults: Activation key is created, updated to limited host

    :parametrized: yes
    """
    # unlimited_hosts defaults to True.
    act_key = target_sat.api.ActivationKey().create()
    want = {'max_hosts': max_host, 'unlimited_hosts': False}
    for key, value in want.items():
        setattr(act_key, key, value)
    act_key = act_key.update(want.keys())
    actual = {attr: getattr(act_key, attr) for attr in want}
    assert want == actual


@pytest.mark.parametrize('new_name', **parametrized(valid_data_list()))
def test_positive_update_name(new_name, target_sat, module_org):
    """Create activation key providing the initial name, then update
    its name to another valid name.

    :id: f219f2dc-8759-43ab-a277-fbabede6795e

    :expectedresults: Activation key is created, and its name can be
        updated.

    :parametrized: yes
    """
    act_key = target_sat.api.ActivationKey(organization=module_org).create()
    updated = target_sat.api.ActivationKey(
        id=act_key.id, organization=module_org, name=new_name
    ).update(['name'])
    assert new_name == updated.name


@pytest.mark.parametrize('max_host', **parametrized(_bad_max_hosts()))
def test_negative_update_limit(max_host, target_sat):
    """Create activation key then update its limit to invalid value.

    :id: 0f857d2f-81ed-4b8b-b26e-34b4f294edbc

    :expectedresults:

        1. Activation key is created
        2. Update fails
        3. Record is not changed

    :CaseImportance: Low

    :parametrized: yes
    """
    act_key = target_sat.api.ActivationKey().create()
    want = {'max_hosts': act_key.max_hosts, 'unlimited_hosts': act_key.unlimited_hosts}
    act_key.max_hosts = max_host
    act_key.unlimited_hosts = False
    with pytest.raises(HTTPError):
        act_key.update(want.keys())
    act_key = act_key.read()
    actual = {attr: getattr(act_key, attr) for attr in want}
    assert want == actual


@pytest.mark.parametrize('new_name', **parametrized(invalid_names_list()))
def test_negative_update_name(new_name, target_sat, module_org):
    """Create activation key then update its name to an invalid name.

    :id: da85a32c-942b-4ab8-a133-36b028208c4d

    :expectedresults: Activation key is created, and its name is not
        updated.

    :CaseImportance: Low

    :parametrized: yes
    """
    act_key = target_sat.api.ActivationKey(organization=module_org).create()
    with pytest.raises(HTTPError):
        target_sat.api.ActivationKey(id=act_key.id, organization=module_org, name=new_name).update(
            ['name']
        )
    new_key = target_sat.api.ActivationKey(id=act_key.id).read()
    assert new_key.name != new_name
    assert new_key.name == act_key.name


def test_negative_update_max_hosts(target_sat, module_org):
    """Create an activation key with ``max_hosts == 1``, then update that
    field with a string value.

    :id: 3bcff792-105a-4577-b7c2-5b0de4f79c77

    :expectedresults: The update fails with an HTTP 422 return code.

    :CaseImportance: Low
    """
    act_key = target_sat.api.ActivationKey(max_hosts=1, organization=module_org).create()
    with pytest.raises(HTTPError):
        target_sat.api.ActivationKey(
            id=act_key.id, organization=module_org, max_hosts='foo'
        ).update(['max_hosts'])
    assert act_key.read().max_hosts == 1


def test_positive_get_releases_status_code(target_sat):
    """Get an activation key's releases. Check response format.

    :id: e1ea4797-8d92-4bec-ae6b-7a26599825ab

    :expectedresults: HTTP 200 is returned with an ``application/json``
        content-type
    """
    act_key = target_sat.api.ActivationKey().create()
    path = act_key.path('releases')
    response = client.get(path, auth=get_credentials(), verify=False)
    status_code = http.client.OK
    assert status_code == response.status_code
    assert 'application/json' in response.headers['content-type']


def test_positive_get_releases_content(target_sat):
    """Get an activation key's releases. Check response contents.

    :id: 2fec3d71-33e9-40e5-b934-90b03afc26a1

    :expectedresults: A list of results is returned.
    """
    act_key = target_sat.api.ActivationKey().create()
    response = client.get(act_key.path('releases'), auth=get_credentials(), verify=False).json()
    assert 'results' in response
    assert isinstance(response['results'], list)


def test_positive_add_host_collections(module_org, module_target_sat):
    """Associate an activation key with several host collections.

    :id: 1538808c-621e-4cf9-9b9b-840c5dd54644

    :expectedresults:

        1. By default, an activation key is associated with no host
           collections.
        2. After associating an activation key with some set of host
           collections and reading that activation key, the correct host
           collections are listed.

    :CaseImportance: Critical
    """
    # An activation key has no host collections by default.
    act_key = module_target_sat.api.ActivationKey(organization=module_org).create()
    assert len(act_key.host_collection) == 0

    # Give activation key one host collection.
    act_key.host_collection.append(
        module_target_sat.api.HostCollection(organization=module_org).create()
    )
    act_key = act_key.update(['host_collection'])
    assert len(act_key.host_collection) == 1

    # Give activation key second host collection.
    act_key.host_collection.append(
        module_target_sat.api.HostCollection(organization=module_org).create()
    )
    act_key = act_key.update(['host_collection'])
    assert len(act_key.host_collection) == 2


@pytest.mark.upgrade
def test_positive_remove_host_collection(module_org, module_target_sat):
    """Disassociate host collection from the activation key

    :id: 31992ac4-fe55-45bb-bd17-a191928ec2ab

    :expectedresults:

        1. By default, an activation key is associated with no host
           collections.
        2. Associating host collection with activation key add it to the
           list.
        3. Disassociating host collection from the activation key actually
           removes it from the list

    :CaseImportance: Critical
    """
    # An activation key has no host collections by default.
    act_key = module_target_sat.api.ActivationKey(organization=module_org).create()
    assert len(act_key.host_collection) == 0

    host_collection = module_target_sat.api.HostCollection(organization=module_org).create()

    # Associate host collection with activation key.
    act_key.add_host_collection(data={'host_collection_ids': [host_collection.id]})
    assert len(act_key.read().host_collection) == 1

    # Disassociate host collection from the activation key.
    act_key.remove_host_collection(data={'host_collection_ids': [host_collection.id]})
    assert len(act_key.read().host_collection) == 0


def test_positive_update_auto_attach(target_sat, module_org):
    """Create an activation key, then update the auto_attach
    field with the inverse boolean value.

    :id: ec225dad-2d27-4b37-989d-1ba2c7f74ac4

    :expectedresults: The value is changed.

    :CaseImportance: Critical
    """
    act_key = target_sat.api.ActivationKey(organization=module_org).create()
    act_key_2 = target_sat.api.ActivationKey(
        id=act_key.id, organization=module_org, auto_attach=(not act_key.auto_attach)
    ).update(['auto_attach'])
    assert act_key.auto_attach != act_key_2.auto_attach


@pytest.mark.upgrade
@pytest.mark.parametrize('name', **parametrized(valid_data_list()))
def test_positive_delete(name, target_sat):
    """Create activation key and then delete it.

    :id: aa28d8fb-e07d-45fa-b43a-fc90c706d633

    :expectedresults: Activation key is successfully deleted.

    :CaseImportance: Critical

    :parametrized: yes
    """
    act_key = target_sat.api.ActivationKey(name=name).create()
    act_key.delete()
    with pytest.raises(HTTPError):
        target_sat.api.ActivationKey(id=act_key.id).read()


def test_positive_remove_user(target_sat):
    """Delete any user who has previously created an activation key
    and check that activation key still exists

    :id: 02ce92d4-8f49-48a0-bf9e-5d401f84cf46

    :expectedresults: Activation Key can be read

    :BZ: 1291271
    """
    password = gen_string('alpha')
    user = target_sat.api.User(password=password, login=gen_string('alpha'), admin=True).create()
    user_cfg = user_nailgun_config(user.login, password)
    ak = target_sat.api.ActivationKey(server_config=user_cfg).create()
    user.delete()
    try:
        target_sat.api.ActivationKey(id=ak.id).read()
    except HTTPError:
        pytest.fail("Activation Key can't be read")


@pytest.mark.upgrade
@pytest.mark.run_in_one_thread
def test_positive_fetch_product_content(
    module_org, module_lce, module_sca_manifest, module_target_sat
):
    """Associate RH & custom product with AK and fetch AK's product content

    :id: 481a29fc-d8ae-423f-a980-911be9247187

    :expectedresults: Both Red Hat and custom product repositories are
        assigned as Activation Key's product content

    :CaseImportance: Critical
    """
    module_target_sat.upload_manifest(module_org.id, module_sca_manifest.content)
    rh_repo_id = module_target_sat.api_factory.enable_rhrepo_and_fetchid(
        basearch='x86_64',
        org_id=module_org.id,
        product=PRDS['rhel'],
        repo=REPOS['rhst7']['name'],
        reposet=REPOSET['rhst7'],
        releasever=None,
    )
    rh_repo = module_target_sat.api.Repository(id=rh_repo_id).read()
    rh_repo.sync()
    custom_repo = module_target_sat.api.Repository(
        product=module_target_sat.api.Product(organization=module_org).create()
    ).create()
    custom_repo.sync()
    cv = module_target_sat.api.ContentView(
        organization=module_org, repository=[rh_repo_id, custom_repo.id]
    ).create()
    cv.publish()
    cv = cv.read()
    cvv = cv.version[0]
    cvv.promote(data={'environment_ids': module_lce.id})

    ak = module_target_sat.api.ActivationKey(
        content_view=cv.id, organization=module_org.id, environment=module_lce.id
    ).create()
    ak_content = ak.product_content()['results']
    assert {custom_repo.product.id, rh_repo.product.id} == {
        repos['product']['id'] for repos in ak_content
    }


def test_positive_search_by_org(target_sat):
    """Search for all activation keys in an organization.

    :id: aedba598-2e47-44a8-826c-4dc304ba00be

    :expectedresults: Only activation keys in the organization are
        returned.

    :CaseImportance: Critical
    """
    org = target_sat.api.Organization().create()
    act_key = target_sat.api.ActivationKey(organization=org).create()
    keys = target_sat.api.ActivationKey(organization=org).search()
    assert len(keys) == 1
    assert act_key.id == keys[0].id
