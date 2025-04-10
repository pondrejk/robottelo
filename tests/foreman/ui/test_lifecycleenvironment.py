"""Test class for Lifecycle Environment UI

:Requirement: Lifecycleenvironment

:CaseAutomation: Automated

:CaseComponent: LifecycleEnvironments

:team: Phoenix-content

:CaseImportance: High

"""

from navmazing import NavigationTriesExceeded
import pytest

from robottelo.config import settings
from robottelo.constants import (
    ENVIRONMENT,
    FAKE_0_CUSTOM_PACKAGE,
    FAKE_0_CUSTOM_PACKAGE_NAME,
    FAKE_1_CUSTOM_PACKAGE,
    FAKE_1_CUSTOM_PACKAGE_NAME,
    FAKE_2_CUSTOM_PACKAGE,
    FAKE_3_CUSTOM_PACKAGE_NAME,
)
from robottelo.utils.datafactory import gen_string


@pytest.mark.upgrade
def test_positive_end_to_end(session):
    """Perform end to end testing for lifecycle environment component

    :id: b2293de9-7a71-462e-b988-321b07c01642

    :expectedresults: All expected CRUD actions finished successfully

    :CaseImportance: High
    """
    lce_name = gen_string('alpha')
    new_lce_name = gen_string('alpha')
    label = gen_string('alpha')
    description = gen_string('alpha')
    with session:
        # Create new lce
        session.lifecycleenvironment.create(
            {'name': lce_name, 'label': label, 'description': description}
        )
        lce_values = session.lifecycleenvironment.read(lce_name)
        assert lce_values['details']['name'] == lce_name
        assert lce_values['details']['label'] == label
        assert lce_values['details']['description'] == description
        assert lce_values['details']['unauthenticated_pull'] == 'No'
        # Update lce with new name
        session.lifecycleenvironment.update(lce_name, {'details.name': new_lce_name})
        lce_values = session.lifecycleenvironment.read_all()
        assert new_lce_name in lce_values['lce']
        assert lce_name not in lce_values['lce']
        # Delete lce
        session.lifecycleenvironment.delete(new_lce_name)
        lce_values = session.lifecycleenvironment.read_all()
        assert new_lce_name not in lce_values['lce']


@pytest.mark.upgrade
def test_positive_create_chain(session):
    """Create Content Environment in a chain

    :id: ed3d2c88-ef0a-4a1a-9f11-5bdb2119fc18

    :expectedresults: Environment is created
    """
    lce_path_name = gen_string('alpha')
    lce_name = gen_string('alpha')
    with session:
        session.lifecycleenvironment.create(values={'name': lce_path_name})
        session.lifecycleenvironment.create(
            values={'name': lce_name}, prior_entity_name=lce_path_name
        )
        lce_values = session.lifecycleenvironment.read_all()
        assert lce_name in lce_values['lce']
        assert lce_path_name in lce_values['lce'][lce_name]


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_search_lce_content_view_packages_by_full_name(session, module_org, target_sat):
    """Search Lifecycle Environment content view packages by full name

    Note: if package full name looks like "bear-4.1-1.noarch",
        eg. name-version-release-arch, the package name is "bear"

    :id: fad05fe9-b673-4384-b65a-926d4a0d2598

    :customerscenario: true

    :steps:
        1. Create a product with a repository synchronized
            - The repository must contain at least two package names P1 and
              P2
            - P1 has only one package
            - P2 has two packages
        2. Create a content view with the repository and publish it
        3. Go to Lifecycle Environment > Library > Packages
        4. Select the content view
        5. Search by packages using full names

    :expectedresults: only the searched packages where found

    :BZ: 1432155
    """
    packages = [
        {'name': FAKE_0_CUSTOM_PACKAGE_NAME, 'full_names': [FAKE_0_CUSTOM_PACKAGE]},
        {
            'name': FAKE_1_CUSTOM_PACKAGE_NAME,
            'full_names': [FAKE_1_CUSTOM_PACKAGE, FAKE_2_CUSTOM_PACKAGE],
        },
    ]
    product = target_sat.api.Product(organization=module_org).create()
    repository = target_sat.api.Repository(product=product, url=settings.repos.yum_0.url).create()
    repository.sync()
    content_view = target_sat.api.ContentView(
        organization=module_org, repository=[repository]
    ).create()
    content_view.publish()
    with session:
        for package in packages:
            for package_full_name in package['full_names']:
                result = session.lifecycleenvironment.search_package(
                    ENVIRONMENT, package_full_name, cv_name=content_view.name
                )
                assert len(result) == 1
                assert result[0]['Name'] == package['name']


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_search_lce_content_view_packages_by_name(session, module_org, target_sat):
    """Search Lifecycle Environment content view packages by name

    Note: if package full name looks like "bear-4.1-1.noarch",
        eg. name-version-release-arch, the package name is "bear"

    :id: f8dec2a8-8971-44ad-a4d5-1eb5d2eb62f6

    :customerscenario: true

    :steps:
        1. Create a product with a repository synchronized
            - The repository must contain at least two package names P1 and
              P2
            - P1 has only one package
            - P2 has two packages
        2. Create a content view with the repository and publish it
        3. Go to Lifecycle Environment > Library > Packages
        4. Select the content view
        5. Search by package names

    :expectedresults: only the searched packages where found

    :BZ: 1432155
    """
    packages = [
        {'name': FAKE_0_CUSTOM_PACKAGE_NAME, 'packages_count': 1},
        {'name': FAKE_1_CUSTOM_PACKAGE_NAME, 'packages_count': 2},
    ]
    product = target_sat.api.Product(organization=module_org).create()
    repository = target_sat.api.Repository(product=product, url=settings.repos.yum_0.url).create()
    repository.sync()
    content_view = target_sat.api.ContentView(
        organization=module_org, repository=[repository]
    ).create()
    content_view.publish()
    with session:
        for package in packages:
            result = session.lifecycleenvironment.search_package(
                ENVIRONMENT, package['name'], cv_name=content_view.name
            )
            assert len(result) == package['packages_count']
            for entry in result:
                assert entry['Name'].startswith(package['name'])


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_search_lce_content_view_module_streams_by_name(session, module_org, target_sat):
    """Search Lifecycle Environment content view module streams by name

    :id: e67893b2-a56e-4eac-87e6-63be897ba912

    :customerscenario: true

    :steps:
        1. Create a product with a repository synchronized
            - The repository must contain at least two module stream names P1 and
              P2
            - P1 has two module streams
            - P2 has three module streams
        2. Create a content view with the repository and publish it
        3. Go to Lifecycle Environment > Library > ModuleStreams
        4. Select the content view
        5. Search by module stream names

    :expectedresults: only the searched module streams where found
    """
    module_streams = [
        {'name': FAKE_1_CUSTOM_PACKAGE_NAME, 'streams_count': 2},
        {'name': FAKE_3_CUSTOM_PACKAGE_NAME, 'streams_count': 3},
    ]
    product = target_sat.api.Product(organization=module_org).create()
    repository = target_sat.api.Repository(
        product=product, url=settings.repos.module_stream_1.url
    ).create()
    repository.sync()
    content_view = target_sat.api.ContentView(
        organization=module_org, repository=[repository]
    ).create()
    content_view.publish()
    with session:
        for module in module_streams:
            result = session.lifecycleenvironment.search_module_stream(
                ENVIRONMENT, module['name'], cv_name=content_view.name
            )
            assert len(result) == module['streams_count']
            for entry in result:
                assert entry['Name'].startswith(module['name'])


@pytest.mark.upgrade
def test_positive_custom_user_view_lce(session, test_name, target_sat):
    """As a custom user attempt to view a lifecycle environment created
    by admin user

    :id: 768b647b-c530-4eca-9caa-38cf8622f36d

    :BZ: 1420511

    :steps:

        As an admin user:

        1. Create an additional lifecycle environments other than Library
        2. Create a user without administrator privileges
        3. Create a role with the the following permissions:

            * (Miscellaneous): access_dashboard
            * Lifecycle Environment:

            * edit_lifecycle_environments
            * promote_or_remove_content_views_to_environment
            * view_lifecycle_environments

            * Location: view_locations
            * Organization: view_organizations

        4. Assign the created role to the custom user

        As a custom user:

        1. Log in
        2. Navigate to Content -> Lifecycle Environments

    :expectedresults: The additional lifecycle environment is viewable and
        accessible by the custom user.
    """
    role_name = gen_string('alpha')
    lce_name = gen_string('alpha')
    user_login = gen_string('alpha')
    user_password = gen_string('alpha')
    org = target_sat.api.Organization().create()
    role = target_sat.api.Role(name=role_name).create()
    permissions_types_names = {
        None: ['access_dashboard'],
        'Organization': ['view_organizations'],
        'Location': ['view_locations'],
        'Katello::KTEnvironment': [
            'view_lifecycle_environments',
            'edit_lifecycle_environments',
            'promote_or_remove_content_views_to_environments',
        ],
    }
    target_sat.api_factory.create_role_permissions(role, permissions_types_names)
    target_sat.api.User(
        default_organization=org,
        organization=[org],
        role=[role],
        login=user_login,
        password=user_password,
    ).create()
    # create a life cycle environment as admin user and ensure it's visible
    with session:
        session.organization.select(org.name)
        session.lifecycleenvironment.create(values={'name': lce_name})
        lce_values = session.lifecycleenvironment.read_all()
        assert lce_name in lce_values['lce']
    # ensure the created user also can find the created lifecycle environment link
    with target_sat.ui_session(test_name, user_login, user_password) as non_admin_session:
        # to ensure that the created user has only the assigned
        # permissions, check that hosts menu tab does not exist
        with pytest.raises(NavigationTriesExceeded):
            assert not non_admin_session.host.read_all()
        # assert that the user can view the lvce created by admin user
        lce_values = non_admin_session.lifecycleenvironment.read_all()
        assert lce_name in lce_values['lce']
