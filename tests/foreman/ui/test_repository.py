"""Test module for Repository UI

:Requirement: Repository

:CaseAutomation: Automated

:CaseComponent: Repositories

:team: Phoenix-content

:CaseImportance: High

"""

from datetime import UTC, datetime, timedelta
from random import choice, randint, shuffle

from navmazing import NavigationTriesExceeded
import pytest

from robottelo import constants
from robottelo.config import settings
from robottelo.constants import (
    DOWNLOAD_POLICIES,
    INVALID_URL,
    PRDS,
    RECOMMENDED_REPOS,
    REPO_TYPE,
    REPOS,
    REPOSET,
    SUPPORTED_REPO_CHECKSUMS,
    VERSIONED_REPOS,
    DataFile,
)
from robottelo.constants.repos import (
    ANSIBLE_GALAXY,
    CUSTOM_RPM_SHA,
)
from robottelo.hosts import get_sat_version
from robottelo.utils.datafactory import gen_string


@pytest.fixture(scope='module')
def module_org(module_target_sat):
    return module_target_sat.api.Organization().create()


@pytest.fixture(scope='module')
def module_prod(module_org, module_target_sat):
    return module_target_sat.api.Product(organization=module_org).create()


@pytest.mark.upgrade
@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_create_in_different_orgs(session, module_org, module_target_sat):
    """Create repository in two different orgs with same name

    :id: 019c2242-8802-4bae-82c5-accf8f793dbc

    :expectedresults: Repository is created successfully for both
        organizations
    """
    repo_name = gen_string('alpha')
    org2 = module_target_sat.api.Organization().create()
    prod1 = module_target_sat.api.Product(organization=module_org).create()
    prod2 = module_target_sat.api.Product(organization=org2).create()
    with session:
        for org, prod in [[module_org, prod1], [org2, prod2]]:
            session.organization.select(org_name=org.name)
            session.repository.create(
                prod.name,
                {
                    'name': repo_name,
                    'label': org.label,
                    'repo_type': REPO_TYPE['yum'],
                    'repo_content.upstream_url': settings.repos.yum_1.url,
                },
            )
            assert session.repository.search(prod.name, repo_name)[0]['Name'] == repo_name
            values = session.repository.read(prod.name, repo_name)
            assert values['name'] == repo_name
            assert values['label'] == org.label


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_create_as_non_admin_user(module_org, test_name, target_sat):
    """Create a repository as a non admin user

    :id: 582949c4-b95f-4d64-b7f0-fb80b3d2bd7e

    :expectedresults: Repository successfully created

    :BZ: 1426393
    """
    user_login = gen_string('alpha')
    user_password = gen_string('alphanumeric')
    repo_name = gen_string('alpha')
    user_permissions = {
        None: ['access_dashboard'],
        'Katello::Product': [
            'view_products',
            'create_products',
            'edit_products',
            'destroy_products',
            'sync_products',
        ],
    }
    role = target_sat.api.Role().create()
    target_sat.api_factory.create_role_permissions(role, user_permissions)
    target_sat.api.User(
        login=user_login,
        password=user_password,
        role=[role],
        admin=False,
        default_organization=module_org,
        organization=[module_org],
    ).create()
    product = target_sat.api.Product(organization=module_org).create()
    with target_sat.ui_session(test_name, user=user_login, password=user_password) as session:
        # ensure that the created user is not a global admin user
        # check administer->organizations page
        with pytest.raises(NavigationTriesExceeded):
            session.organization.create({'name': gen_string('alpha'), 'label': gen_string('alpha')})
        session.repository.create(
            product.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['yum'],
                'repo_content.upstream_url': settings.repos.yum_1.url,
            },
        )
        assert session.repository.search(product.name, repo_name)[0]['Name'] == repo_name


@pytest.mark.upgrade
@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_create_yum_repo_same_url_different_orgs(session, module_prod, module_target_sat):
    """Create two repos with the same URL in two different organizations.

    :id: f4cb00ed-6faf-4c79-9f66-76cd333299cb

    :expectedresults: Repositories are created and have equal number of packages.
    """
    # Create first repository
    repo = module_target_sat.api.Repository(
        product=module_prod, url=settings.repos.yum_0.url
    ).create()
    repo.sync()
    # Create second repository
    org = module_target_sat.api.Organization().create()
    product = module_target_sat.api.Product(organization=org).create()
    new_repo = module_target_sat.api.Repository(
        product=product, url=settings.repos.yum_0.url
    ).create()
    new_repo.sync()
    with session:
        # Check packages number in first repository
        assert session.repository.search(module_prod.name, repo.name)[0]['Name'] == repo.name
        repo = session.repository.read(module_prod.name, repo.name)
        repo_packages_count = repo['content_counts']['Packages']
        assert int(repo_packages_count) >= int('1')

        # Check packages number in first repository
        session.organization.select(org.name)
        assert session.repository.search(product.name, new_repo.name)[0]['Name'] == new_repo.name
        new_repo = session.repository.read(product.name, new_repo.name)
        new_repo_packages_count = new_repo['content_counts']['Packages']
        assert int(new_repo_packages_count) >= int('1')
        assert repo_packages_count == new_repo_packages_count


@pytest.mark.upgrade
@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_create_as_non_admin_user_with_cv_published(module_org, test_name, target_sat):
    """Create a repository as a non admin user in a product that already
    contain a repository that is used in a published content view.

    :id: 407864eb-50b8-4bc8-bbc7-0e6f8136d89f

    :expectedresults: New repository successfully created by non admin user

    :BZ: 1447829
    """
    user_login = gen_string('alpha')
    user_password = gen_string('alphanumeric')
    repo_name = gen_string('alpha')
    user_permissions = {
        None: ['access_dashboard'],
        'Katello::Product': [
            'view_products',
            'create_products',
            'edit_products',
            'destroy_products',
            'sync_products',
        ],
    }
    role = target_sat.api.Role().create()
    target_sat.api_factory.create_role_permissions(role, user_permissions)
    target_sat.api.User(
        login=user_login,
        password=user_password,
        role=[role],
        admin=False,
        default_organization=module_org,
        organization=[module_org],
    ).create()
    prod = target_sat.api.Product(organization=module_org).create()
    repo = target_sat.api.Repository(product=prod, url=settings.repos.yum_2.url).create()
    repo.sync()
    content_view = target_sat.api.ContentView(organization=module_org).create()
    content_view.repository = [repo]
    content_view = content_view.update(['repository'])
    content_view.publish()
    with target_sat.ui_session(test_name, user_login, user_password) as session:
        # ensure that the created user is not a global admin user
        # check administer->users page
        pswd = gen_string('alphanumeric')
        with pytest.raises(NavigationTriesExceeded):
            session.user.create(
                {
                    'user.login': gen_string('alphanumeric'),
                    'user.auth': 'INTERNAL',
                    'user.password': pswd,
                    'user.confirm': pswd,
                }
            )
        # ensure that the created user has only the assigned permissions
        # check that host collections menu tab does not exist
        with pytest.raises(NavigationTriesExceeded):
            session.hostcollection.create({'name': gen_string('alphanumeric')})
        session.repository.create(
            prod.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['yum'],
                'repo_content.upstream_url': settings.repos.yum_1.url,
            },
        )
        assert session.repository.search(prod.name, repo.name)[0]['Name'] == repo.name


@pytest.mark.upgrade
@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
@pytest.mark.usefixtures('allow_repo_discovery')
def test_positive_discover_repo_via_new_and_existing_product(
    session, module_org, module_target_sat
):
    """Create repository via repo discovery under new product and existing product

    :id: d8828eca-5ac5-4507-884c-581b8a39dbe1

    :expectedresults: Repository is discovered and created for new product and existing product as well
    """
    product_name = gen_string('alpha')
    repo_name = 'fakerepo01'
    repo_path = '/pulp/demo_repos/large_errata/'
    repo_name_1 = 'zoo'
    repo_url = settings.robottelo.REPOS_HOSTING_URL + repo_path
    with session:
        session.organization.select(org_name=module_org.name)
        # Discover repo via new product
        session.product.discover_repo(
            {
                'repo_type': 'Yum Repositories',
                'url': settings.repos.repo_discovery.url,
                'discovered_repos.repos': repo_name,
                'create_repo.product_type': 'New Product',
                'create_repo.product_content.product_name': product_name,
            }
        )
        assert session.product.search(product_name)[0]['Name'] == product_name
        assert repo_name in session.repository.search(product_name, repo_name)[0]['Name']

        # Discover repo via existing product
        session.product.discover_repo(
            {
                'repo_type': 'Yum Repositories',
                'url': repo_url,
                'discovered_repos.repos': repo_name_1,
                'create_repo.product_type': 'Existing Product',
                'create_repo.product_content.product_name': product_name,
            }
        )
        assert repo_name_1 in session.repository.search(product_name, repo_name_1)[0]['Name']


@pytest.mark.upgrade
@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_sync_yum_repo_and_verify_content_checksum(session, module_org, module_target_sat):
    """Create Custom yum repos, sync it via the repos page and verify content checksum succeeds when
    executing from the products page

    :id: 44a66ea2-aa77-4fcc-8c14-ee82df36ff92

    :customerscenario: true

    :BZ: 1951626

    :steps:
        1. Create Product, create yum repo, enable and sync repository
        2. Go to Products -> Select Action -> Verify Content Checksum

    :expectedresults: Sync procedure for yum repository and verify Content Checksum task successful
    """
    product = module_target_sat.api.Product(organization=module_org).create()
    repo = module_target_sat.api.Repository(url=settings.repos.yum_1.url, product=product).create()
    with session:
        result = session.repository.synchronize(product.name, repo.name)
        assert result['result'] == 'success'
        sync_values = session.dashboard.read('SyncOverview')['syncs']
        assert len(sync_values) >= 1
        for sync_val in sync_values:
            if 'less than a minute ago' in sync_val['Finished']:
                assert sync_val['Product'] == product.name
                assert sync_val['Status'] == 'Syncing Complete.'
        result = session.product.verify_content_checksum([product.name])
        assert result['task']['result'] == 'success'


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_resync_custom_repo_after_invalid_update(session, module_org, module_target_sat):
    """Create Custom yum repo and sync it via the repos page. Then try to
    change repo url to invalid one and re-sync that repository

    :id: 089b1e41-2017-429a-9c3f-b0291007a78f

    :customerscenario: true

    :expectedresults: Repository URL is not changed to invalid value and resync
        procedure for specific yum repository is successful

    :BZ: 1487173, 1262313
    """
    product = module_target_sat.api.Product(organization=module_org).create()
    repo = module_target_sat.api.Repository(url=settings.repos.yum_1.url, product=product).create()
    with session:
        result = session.repository.synchronize(product.name, repo.name)
        assert result['result'] == 'success'
        with pytest.raises(AssertionError) as context:
            session.repository.update(
                product.name, repo.name, {'repo_content.upstream_url': INVALID_URL}
            )
        assert 'bad URI(is not URI?)' in str(context.value)
        assert session.repository.search(product.name, repo.name)[0]['Name'] == repo.name
        repo_values = session.repository.read(product.name, repo.name)
        assert repo_values['repo_content']['upstream_url'] == settings.repos.yum_1.url
        result = session.repository.synchronize(product.name, repo.name)
        assert result['result'] == 'success'


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_resynchronize_rpm_repo(session, module_prod, module_target_sat):
    """Check that repository content is resynced after packages were removed
    from repository

    :id: dc415563-c9b8-4e3c-9d2a-f4ac251c7d35

    :expectedresults: Repository has updated non-zero package count

    :BZ: 1318004
    """
    repo = module_target_sat.api.Repository(
        url=settings.repos.yum_1.url, content_type=REPO_TYPE['yum'], product=module_prod
    ).create()
    with session:
        result = session.repository.synchronize(module_prod.name, repo.name)
        assert result['result'] == 'success'
        # Check packages count
        repo_values = session.repository.read(module_prod.name, repo.name)
        assert int(repo_values['content_counts']['Packages']) >= 1
        # Remove packages
        session.repository.remove_all_packages(module_prod.name, repo.name)
        repo_values = session.repository.read(module_prod.name, repo.name)
        assert repo_values['content_counts']['Packages'] == '0'
        # Sync it again
        result = session.repository.synchronize(module_prod.name, repo.name)
        assert result['result'] == 'success'
        # Check packages number
        repo_values = session.repository.read(module_prod.name, repo.name)
        assert int(repo_values['content_counts']['Packages']) >= 1


@pytest.mark.upgrade
@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_end_to_end_custom_yum_crud(session, module_org, module_prod, module_target_sat):
    """Perform end to end testing for custom yum repository

    :id: 8baf11c9-019e-4625-a549-ec4cd9312f75

    :expectedresults: All expected CRUD actions finished successfully

    :CaseImportance: High
    """
    repo_name = gen_string('alpha')
    checksum_type = choice(SUPPORTED_REPO_CHECKSUMS)
    new_repo_name = gen_string('alphanumeric')
    new_checksum_type = choice([cs for cs in SUPPORTED_REPO_CHECKSUMS if cs != checksum_type])
    gpg_key = module_target_sat.api.GPGKey(
        content=DataFile.VALID_GPG_KEY_FILE.read_text(),
        organization=module_org,
    ).create()
    new_gpg_key = module_target_sat.api.GPGKey(
        content=DataFile.VALID_GPG_KEY_BETA_FILE.read_text(),
        organization=module_org,
    ).create()
    with session:
        session.repository.create(
            module_prod.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['yum'],
                'repo_content.upstream_url': settings.repos.yum_1.url,
                'repo_content.checksum_type': checksum_type,
                'repo_content.gpg_key': gpg_key.name,
                'repo_content.download_policy': DOWNLOAD_POLICIES['immediate'],
            },
        )
        assert session.repository.search(module_prod.name, repo_name)[0]['Name'] == repo_name
        repo_values = session.repository.read(module_prod.name, repo_name)
        assert repo_values['repo_content']['upstream_url'] == settings.repos.yum_1.url
        assert repo_values['repo_content']['metadata_type'] == checksum_type
        assert repo_values['repo_content']['gpg_key'] == gpg_key.name
        assert repo_values['repo_content']['download_policy'] == DOWNLOAD_POLICIES['immediate']
        session.repository.update(
            module_prod.name,
            repo_name,
            {
                'name': new_repo_name,
                'repo_content.upstream_url': settings.repos.yum_2.url,
                'repo_content.metadata_type': new_checksum_type,
                'repo_content.gpg_key': new_gpg_key.name,
                'repo_content.download_policy': DOWNLOAD_POLICIES['immediate'],
            },
        )
        assert not session.repository.search(module_prod.name, repo_name)
        repo_values = session.repository.read(module_prod.name, new_repo_name)
        assert repo_values['name'] == new_repo_name
        assert repo_values['repo_content']['upstream_url'] == settings.repos.yum_2.url
        assert repo_values['repo_content']['metadata_type'] == new_checksum_type
        assert repo_values['repo_content']['gpg_key'] == new_gpg_key.name
        assert repo_values['repo_content']['download_policy'] == DOWNLOAD_POLICIES['immediate']
        session.repository.delete(module_prod.name, new_repo_name)
        assert not session.repository.search(module_prod.name, new_repo_name)


@pytest.mark.upgrade
@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_positive_end_to_end_custom_module_streams_crud(session, module_org, module_prod):
    """Perform end to end testing for custom module streams yum repository

    :id: ea0a58ae-b280-4bca-8f22-cbed73453604

    :expectedresults: All expected CRUD actions finished successfully

    :CaseImportance: High
    """
    repo_name = gen_string('alpha')
    with session:
        session.repository.create(
            module_prod.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['yum'],
                'repo_content.upstream_url': settings.repos.module_stream_1.url,
            },
        )
        assert session.repository.search(module_prod.name, repo_name)[0]['Name'] == repo_name
        repo_values = session.repository.read(module_prod.name, repo_name)
        assert repo_values['repo_content']['upstream_url'] == settings.repos.module_stream_1.url
        result = session.repository.synchronize(module_prod.name, repo_name)
        assert result['result'] == 'success'
        repo_values = session.repository.read(module_prod.name, repo_name)
        assert int(repo_values['content_counts']['Module Streams']) >= 5
        session.repository.update(
            module_prod.name,
            repo_name,
            {'repo_content.upstream_url': settings.repos.module_stream_0.url},
        )
        repo_values = session.repository.read(module_prod.name, repo_name)
        assert repo_values['repo_content']['upstream_url'] == settings.repos.module_stream_0.url
        session.repository.delete(module_prod.name, repo_name)
        assert not session.repository.search(module_prod.name, repo_name)


@pytest.mark.upgrade
def test_positive_upstream_with_credentials(session, module_prod):
    """Create repository with upstream username and password update them and then clear them.

    :id: 141a95f3-79c4-48f8-9c95-e4b128045cb3

    :expectedresults:

        1. The custom repository is created with upstream credentials.
        2. The custom repository upstream credentials are updated.
        3. The credentials are cleared.

    :CaseImportance: High

    :BZ: 1433481, 1743271
    """
    repo_name = gen_string('alpha')
    upstream_username = gen_string('alpha')
    upstream_password = gen_string('alphanumeric')
    new_upstream_username = gen_string('alpha')
    new_upstream_password = gen_string('alphanumeric')
    hidden_password = '*' * 8
    with session:
        session.repository.create(
            module_prod.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['yum'],
                'repo_content.upstream_url': settings.repos.yum_1.url,
                'repo_content.upstream_username': upstream_username,
                'repo_content.upstream_password': upstream_password,
            },
        )
        assert session.repository.search(module_prod.name, repo_name)[0]['Name'] == repo_name
        repo_values = session.repository.read(module_prod.name, repo_name)
        assert (
            repo_values['repo_content']['upstream_authorization']
            == f'{upstream_username} / {hidden_password}'
        )
        session.repository.update(
            module_prod.name,
            repo_name,
            {
                'repo_content.upstream_authorization': dict(
                    username=new_upstream_username, password=new_upstream_password
                )
            },
        )
        repo_values = session.repository.read(module_prod.name, repo_name)
        assert (
            repo_values['repo_content']['upstream_authorization']
            == f'{new_upstream_username} / {hidden_password}'
        )
        session.repository.update(
            module_prod.name, repo_name, {'repo_content.upstream_authorization': {}}
        )
        repo_values = session.repository.read(module_prod.name, repo_name)
        assert not repo_values['repo_content']['upstream_authorization']


# TODO: un-comment when OSTREE functionality is restored in Satellite 6.11
# @pytest.mark.upgrade
# @pytest.mark.skipif(
#   (not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
# def test_positive_end_to_end_custom_ostree_crud(session, module_prod):
#     """Perform end to end testing for custom ostree repository
#
#     :id: 603372aa-60de-44a8-b6c9-3f84c3bbdf05
#
#     :expectedresults: All expected CRUD actions finished successfully
#
#     #
#     :CaseImportance: High
#
#     :BZ: 1467722
#     """
#     repo_name = gen_string('alpha')
#     new_repo_name = gen_string('alphanumeric')
#     with session:
#         session.repository.create(
#             module_prod.name,
#             {
#                 'name': repo_name,
#                 'repo_type': REPO_TYPE['ostree'],
#                 'repo_content.upstream_url': FEDORA_OSTREE_REPO,
#             },
#         )
#         assert session.repository.search(module_prod.name, repo_name)[0]['Name'] == repo_name
#         session.repository.update(
#             module_prod.name,
#             repo_name,
#             {'name': new_repo_name, 'repo_content.upstream_url': FEDORA_OSTREE_REPO},
#         )
#         assert not session.repository.search(module_prod.name, repo_name)
#         repo_values = session.repository.read(module_prod.name, new_repo_name)
#         assert repo_values['name'] == new_repo_name
#         assert repo_values['repo_content']['upstream_url'] == FEDORA_OSTREE_REPO
#         session.repository.delete(module_prod.name, new_repo_name)
#         assert not session.repository.search(module_prod.name, new_repo_name)


@pytest.mark.upgrade
def test_positive_sync_ansible_collection_gallaxy_repo(session, module_prod):
    """Sync ansible collection repository from ansible gallaxy

    :id: f3212dbd-3b8a-49ad-ba03-58f059150c04

    :expectedresults: All content synced successfully

    :CaseImportance: High
    """
    repo_name = f'gallaxy-{gen_string("alpha")}'
    requirements = '''
    ---
    collections:
    - name: theforeman.foreman
      version: "2.1.0"
    - name: theforeman.operations
      version: "0.1.0"
    '''
    with session:
        session.repository.create(
            module_prod.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['ansible_collection'].replace('_', ' '),
                'repo_content.requirements': requirements,
                'repo_content.upstream_url': ANSIBLE_GALAXY,
            },
        )
        result = session.repository.synchronize(module_prod.name, repo_name)
        assert result['result'] == 'success'


def test_positive_no_errors_on_repo_scan(target_sat, function_sca_manifest_org):
    """Scan repos for RHEL Server Extras, then check the production log
    for a specific error

    :id: 443bf4af-7f9a-48b8-8f98-fdb170e8ae88

    :expectedresults: The specific error isn't contained in the prod log

    :customerscenario: True

    :BZ: 1994212
    """
    sat_rpm_extras = target_sat.cli_factory.RHELServerExtras(cdn=True)
    with target_sat.ui_session() as session:
        session.organization.select(function_sca_manifest_org.name)
        session.redhatrepository.read(sat_rpm_extras.data['repository-set'])
        result = target_sat.execute(
            'grep "Failed at scanning for repository: undefined method '
            '`resolve_substitutions\' for nil:NilClass" /var/log/foreman/production.log'
        )
        assert result.status == 1


def test_positive_reposet_disable(session, target_sat, function_sca_manifest_org):
    """Enable RH repo, sync it and then disable

    :id: de596c56-1327-49e8-86d5-a1ab907f26aa

    :expectedresults: RH repo was disabled
    """
    org = function_sca_manifest_org
    sat_tools_repo = target_sat.cli_factory.SatelliteToolsRepository(distro='rhel7', cdn=True)
    repository_name = sat_tools_repo.data['repository']
    with session:
        session.organization.select(org.name)
        session.redhatrepository.enable(
            sat_tools_repo.data['repository-set'],
            sat_tools_repo.data['arch'],
            version=sat_tools_repo.data['releasever'],
        )
        results = session.redhatrepository.search(f'name = "{repository_name}"', category='Enabled')
        assert results[0]['name'] == repository_name
        results = session.sync_status.synchronize(
            [
                (
                    sat_tools_repo.data['product'],
                    sat_tools_repo.data['releasever'],
                    sat_tools_repo.data['arch'],
                    repository_name,
                )
            ]
        )
        assert results
        assert all([result == 'Syncing Complete.' for result in results])
        session.redhatrepository.disable(repository_name)
        assert not session.redhatrepository.search(
            f'name = "{repository_name}"', category='Enabled'
        )


@pytest.mark.run_in_one_thread
def test_positive_reposet_disable_after_manifest_deleted(
    session, function_sca_manifest_org, target_sat
):
    """Enable RH repo and sync it. Remove manifest and then disable
    repository

    :id: f22baa8e-80a4-4487-b1bd-f7265555d9a3

    :customerscenario: true

    :expectedresults: RH repo was disabled

    :BZ: 1344391
    """
    org = function_sca_manifest_org
    sub = target_sat.api.Subscription(organization=org)
    sat_tools_repo = target_sat.cli_factory.SatelliteToolsRepository(distro='rhel7', cdn=True)
    repository_name = sat_tools_repo.data['repository']
    repository_name_orphaned = f'{repository_name} (Orphaned)'
    with session:
        session.organization.select(org.name)
        # Enable RH repository
        session.redhatrepository.enable(
            sat_tools_repo.data['repository-set'],
            sat_tools_repo.data['arch'],
            version=sat_tools_repo.data['releasever'],
        )
        results = session.redhatrepository.search(f'name = "{repository_name}"', category='Enabled')
        assert results[0]['name'] == repository_name
        # Sync the repo and verify sync was successful
        results = session.sync_status.synchronize(
            [
                (
                    sat_tools_repo.data['product'],
                    sat_tools_repo.data['releasever'],
                    sat_tools_repo.data['arch'],
                    repository_name,
                )
            ]
        )
        assert results
        assert all([result == 'Syncing Complete.' for result in results])
        # Delete manifest
        sub.delete_manifest(data={'organization_id': org.id})
        # Verify that the displayed repository name is correct
        results = session.redhatrepository.search(f'name = "{repository_name}"', category='Enabled')
        assert results[0]['name'] == repository_name_orphaned
        # Disable the orphaned repository
        session.redhatrepository.disable(repository_name, orphaned=True)
        assert not session.redhatrepository.search(
            f'name = "{repository_name}"', category='Enabled'
        )


def test_positive_delete_random_docker_repo(session, module_org, module_target_sat):
    """Create Docker-type repositories on multiple products and
    delete a random repository from a random product.

    :id: a3dce435-c46e-41d7-a2f8-29421f7427f5

    :expectedresults: Random repository can be deleted from random product
        without altering the other products.
    """
    entities_list = []
    products = [
        module_target_sat.api.Product(organization=module_org).create()
        for _ in range(randint(2, 5))
    ]
    for product in products:
        repo = module_target_sat.api.Repository(
            url=settings.container.registry_hub, product=product, content_type=REPO_TYPE['docker']
        ).create()
        entities_list.append((product.name, repo.name))
    with session:
        # Delete a random repository
        shuffle(entities_list)
        del_entity = entities_list.pop()
        session.repository.delete(*del_entity)
        # Check whether others repositories are not touched
        for product_name, repo_name in entities_list:
            assert session.repository.search(product_name, repo_name)[0]['Name'] == repo_name


def test_positive_delete_rhel_repo(session, module_sca_manifest_org, target_sat):
    """Enable and sync a Red Hat Repository, and then delete it

    :id: e96f369d-3e58-4824-802e-0b7e99d6d207

    :customerscenario: true

    :expectedresults: Repository can be successfully deleted

    :BZ: 1152672
    """

    sat_tools_repo = target_sat.cli_factory.SatelliteToolsRepository(distro='rhel7', cdn=True)
    repository_name = sat_tools_repo.data['repository']
    product_name = sat_tools_repo.data['product']
    with session:
        session.organization.select(module_sca_manifest_org.name)
        session.redhatrepository.enable(
            sat_tools_repo.data['repository-set'],
            sat_tools_repo.data['arch'],
            version=sat_tools_repo.data['releasever'],
        )
        results = session.redhatrepository.search(f'name = "{repository_name}"', category='Enabled')
        assert results[0]['name'] == repository_name
        results = session.sync_status.synchronize(
            [
                (
                    sat_tools_repo.data['product'],
                    sat_tools_repo.data['releasever'],
                    sat_tools_repo.data['arch'],
                    repository_name,
                )
            ]
        )
        assert results
        assert all([result == 'Syncing Complete.' for result in results])
        session.repository.delete(product_name, repository_name)
        assert not session.redhatrepository.search(
            f'name = "{repository_name}"', category='Enabled'
        )
        assert (
            'Your search returned zero Products' in session.product.search(product_name)[0]['Name']
        )


def test_recommended_repos(session, module_sca_manifest_org):
    """list recommended repositories using On/Off 'Recommended Repositories' toggle.

    :id: 1ae197d5-88ba-4bb1-8ecf-4da5013403d7

    :expectedresults:
           1. Shows repositories as per On/Off 'Recommended Repositories'.
           2. Check last Satellite version of versioned repos do not exist.
           3. Check Client 2 repo is not displayed yet.

    :Verifies: SAT-29446, SAT-29448
    """
    with session:
        session.organization.select(module_sca_manifest_org.name)
        rrepos_on = session.redhatrepository.read(recommended_repo='on')
        v = get_sat_version()

        displayed_repos = [repo['label'] for repo in rrepos_on]
        assert all(repo in displayed_repos for repo in RECOMMENDED_REPOS)
        for repo in VERSIONED_REPOS:
            assert repo.format(f'{v.major}.{v.minor}') in displayed_repos
            assert repo.format(f'{v.major}.{v.minor - 1}') not in displayed_repos

        assert not any('client-2' in label for label in displayed_repos)

        rrepos_off = session.redhatrepository.read(recommended_repo='off')
        assert len(rrepos_off) > len(rrepos_on)


@pytest.mark.stubbed
def test_positive_upload_resigned_rpm():
    """Re-sign and re-upload an rpm that already exists in a repository.

    :id: 75416e72-701a-471c-a0ba-846cf881a1e4

    :expectedresults: New rpm is displayed, old rpm is not displayed in web UI.

    :BZ: 1883722

    :customerscenario: true

    :steps:
        1. Build or prepare an unsigned rpm.
        2. Create a gpg key.
        3. Use the gpg key to sign the rpm with sha1.
        4. Create an rpm repository in the Satellite.
        5. Upload the sha1 signed rpm to the repository.
        6. Use the gpg key to re-sign the rpm with sha2 again.
        7. Upload the sha2 signed rpm to the repository.

    :expectedresults: New rpm is displayed, old rpm is not displayed in web UI.
    """
    pass


@pytest.mark.stubbed
def test_positive_remove_srpm_change_checksum():
    """Re-sync a repository that has had an srpm removed and repodata checksum type changed from
    sha1 to sha256.

    :id: 8bd50cd6-34ac-452d-8654-2792a2613921

    :customerscenario: true

    :BZ: 1850914

    :steps:
        1. Sync a repository that contains rpms and srpms and uses sha1 repodata.
        2. Re-sync the repository after an srpm has been removed and its repodata regenerated
           using sha256.

    :expectedresults: Repository re-syncs successfully, and the removed srpm is no longer visible
        in the UI.
    """
    pass


@pytest.mark.stubbed
def test_positive_repo_discovery_change_ssl():
    """Verify that repository created via repo discovery has expected Verify SSL value.

    :id: 4c3417c8-1aca-4091-bf56-1491e55e4498

    :customerscenario: true

    :BZ: 1789848

    :steps:
        1. Navigate to Content > Products > click on 'Repo Discovery'.
        2. Set the repository type to 'Yum Repositories'.
        3. Enter an upstream URL to discover and click on 'Discover'.
        4. Select the discovered repository and click on 'Create Selected'.
        5. Select the product or create a product.
        6. Un-check the box for 'Verify SSL'.
        7. Enter a repo name and click on 'Run Repository Creation'.

    :expectedresults: New repository has 'Verify SSL' set to False.
    """
    pass


def test_positive_remove_credentials(session, function_product, function_org, function_location):
    """User can remove the upstream_username and upstream_password from a repository in the UI.

    :id: 1d4fc498-1e89-41ae-830f-d239ce389831

    :BZ: 1802158

    :customerscenario: true

    :steps:
        1. Create a custom repository, with a repository type of 'yum' and an upstream username
        and password.
        3. Remove the saved credentials by clicking the delete icon next to the 'Upstream
        Authorization' field in the repository details page.

    :expectedresults: 'Upstream Authorization' value is cleared.
    """
    repo_name = gen_string('alpha')
    upstream_username = gen_string('alpha')
    upstream_password = gen_string('alphanumeric')
    with session:
        session.organization.select(org_name=function_org.name)
        session.location.select(loc_name=function_location.name)
        session.repository.create(
            function_product.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['yum'],
                'repo_content.upstream_url': settings.repos.yum_1.url,
                'repo_content.upstream_username': upstream_username,
                'repo_content.upstream_password': upstream_password,
            },
        )
        session.repository.update(
            function_product.name,
            repo_name,
            {'repo_content.upstream_authorization': False},
        )
        repo_values = session.repository.read(function_product.name, repo_name)
        assert not repo_values['repo_content']['upstream_authorization']


@pytest.mark.skipif((not settings.robottelo.REPOS_HOSTING_URL), reason='Missing repos_hosting_url')
def test_sync_status_persists_after_task_delete(session, module_prod, module_org, target_sat):
    """Red Hat repositories displayed correctly on Sync Status page.

    :id: 29b79d15-9b92-4b6e-a1e4-9bf79de99c9b

    :BZ: 1924625

    :customerscenario: true

    :steps:
        1. Sync a custom Repo.
        2. Navigate to Content > Sync Status. Assert status is Synced.
        3. Use foreman-rake console to delete the Sync task.
        4. Navigate to Content > Sync Status. Assert status is still Synced.

    :expectedresults: Displayed Sync Status is still "Synced" after task deleted.
    """
    # make a note of time for later API wait_for_tasks, and include 4 mins margin of safety.
    timestamp = (datetime.now(UTC) - timedelta(minutes=4)).strftime('%Y-%m-%d %H:%M')
    repo = target_sat.api.Repository(url=settings.repos.yum_1.url, product=module_prod).create()
    with session:
        result = session.sync_status.read()
        result = result['table'][module_prod.name][repo.name]['RESULT']
        assert result == 'Never Synced'
        result = session.sync_status.synchronize([(module_prod.name, repo.name)])
        assert len(result) == 1
        assert result[0] == 'Syncing Complete.'
        # Get the UUID of the sync task.
        search_result = target_sat.wait_for_tasks(
            search_query='label = Actions::Katello::Repository::Sync'
            f' and organization_id = {module_org.id}'
            f' and started_at >= "{timestamp}"',
            search_rate=15,
            max_tries=5,
        )
        # Delete the task using UUID (search_result[0].id)
        task_result = target_sat.execute(
            f"""echo "ForemanTasks::Task.find(
            '{search_result[0].id}').destroy!" | foreman-rake console"""
        )
        assert task_result.status == 0
        # Ensure task record was deleted.
        task_result = target_sat.execute(
            f"""echo "ForemanTasks::Task.find('{search_result[0].id}')" | foreman-rake console"""
        )
        assert task_result.status == 0
        assert 'RecordNotFound' in task_result.stdout
        # Navigate to some other page to ensure we get a refreshed sync status page
        session.repository.read(module_prod.name, repo.name)
        # Read the status again and assert the status is still "Synced".
        result = session.sync_status.read()
        result = result['table'][module_prod.name][repo.name]['RESULT']
        assert 'Synced' in result


@pytest.mark.stubbed
def test_positive_sync_status_repo_display():
    """Red Hat repositories displayed correctly on Sync Status page.

    :id: a9798f9d-ceab-4caf-ab2f-86aa0b7bad8e

    :BZ: 1819794

    :customerscenario: true

    :steps:
        1. Import manifest and enable RHEL 8 repositories.
        2. Navigate to Content > Sync Status.

    :expectedresults: Repositories should be grouped correctly by arch on Sync Status page.
    """
    pass


@pytest.mark.stubbed
def test_positive_search_enabled_kickstart_repos():
    """Red Hat Repositories should show enabled repositories list with search criteria
    'Enabled/Both' and type 'Kickstart'.

    :id: e85a27c1-2600-4f60-af79-c56d49902588

    :customerscenario: true

    :BZ: 1724807, 1829817

    :steps:
        1. Import a manifest
        2. Navigate to Content > Red Hat Repositories, and enable some kickstart repositories.
        3. In the search bar on the right side, select 'Enabled/Both'.
        4. In the filter below the search button, change 'rpm' to 'kickstart'.
        5. Click on 'Search'

    :expectedresults: Enabled repositories should show the list of enabled kickstart repositories.
    """
    pass


@pytest.mark.stubbed
def test_positive_rpm_metadata_display():
    """RPM dependencies should display correctly in UI.

    :id: 308f2f4e-4382-48c9-b606-2c827f91d280

    :customerscenario: true

    :BZ: 1904369

    :steps:
        1. Enable and sync a repository, e.g.,
           'Red Hat Satellite Tools 6.9 for RHEL 7 Server RPMs x86_64'.
        2. Navigate to Content > Packages > click on a package in the repository (e.g.,
           'tfm-rubygem-hammer_cli_foreman_tasks-0.0.15-1.el7sat.noarch') > Dependencies.
        3. Verify that the displayed required and provided capabilities displayed match those of
           the rpm, e.g.,
           tfm-rubygem(hammer_cli_foreman) > 0.0.1.1
           tfm-rubygem(hammer_cli_foreman) < 0.3.0.0
           tfm-rubygem(powerbar) < 0.3.0
           tfm-rubygem(powerbar) >= 0.1.0.11

    :expectedresults: Comparison operators (less than, greater than, etc.) should display
        correctly.
    """
    pass


@pytest.mark.stubbed
def test_positive_select_org_in_any_context():
    """When attempting to check Sync Status from 'Any Context' the user
    should be properly routed away from the 'Select An Organization' page

    :id: 6bd94c3d-1a8b-494b-b1ae-40c17532f8e5

    :customerscenario: true

    :BZ: 1860957

    :steps:
        1. Set "Any organization" and "Any location" on top
        2. Click on Content -> "Sync Status"
        3. "Select an Organization" page will come up.
        4. Select organization in dropdown and press Select

    :expectedresults: After pressing Select, user is navigated to Sync Status page and
        the correct organization should be selected.

    :CaseImportance: High
    """
    pass


def test_positive_sync_sha_repo(session, module_org, module_target_sat):
    """Sync repository with 'sha' checksum, which uses 'sha1' in particular actually

    :id: 6172035f-96c4-41e4-a79b-acfaa78ad734

    :customerscenario: true

    :BZ: 2024889

    :SubComponent: Pulp
    """
    repo_name = gen_string('alpha')
    product = module_target_sat.api.Product(organization=module_org).create()
    with session:
        session.repository.create(
            product.name,
            {
                'name': repo_name,
                'repo_type': REPO_TYPE['yum'],
                'repo_content.upstream_url': CUSTOM_RPM_SHA,
            },
        )
        result = session.repository.synchronize(product.name, repo_name)
        assert result['result'] == 'success'


def test_positive_able_to_disable_and_enable_rhel_repos(
    session, function_sca_manifest_org, target_sat
):
    """Upstream repo name changes shouldn't negatively affect a user's ability
    to enable or disable a repo

    :id: 205a1c05-2ac8-4c60-8d09-016bbcfdf538

    :expectedresults: User is able to enable and disable repos without issues.

    :BZ: 1973329

    :customerscenario: true

    :CaseAutomation: Automated
    """
    # rhel7
    rhel7_repo = target_sat.cli_factory.RHELRepository()
    # enable rhel7 repo
    rhel7_repo.create(function_sca_manifest_org.id, synchronize=False)
    rhel7_repo_name = rhel7_repo.data['repository']
    # reable rhel8_baseos repo
    target_sat.cli.RepositorySet.enable(
        {
            'basearch': constants.DEFAULT_ARCHITECTURE,
            'name': REPOSET['rhel8_bos'],
            'organization-id': function_sca_manifest_org.id,
            'product': PRDS['rhel8'],
            'releasever': REPOS['rhel8_bos']['releasever'],
        }
    )
    rhel8_bos_info = target_sat.cli.RepositorySet.info(
        {
            'name': REPOSET['rhel8_bos'],
            'organization-id': function_sca_manifest_org.id,
            'product': PRDS['rhel8'],
        }
    )
    rhel8_repo_set_name = rhel8_bos_info['enabled-repositories'][0]['name']
    rhel8_repo_name = rhel8_bos_info['name']
    with session:
        # disable and re-enable rhel7
        session.redhatrepository.disable(rhel7_repo_name)
        assert not session.redhatrepository.search(
            f'name = "{rhel7_repo_name}"', category='Enabled'
        )
        session.redhatrepository.enable(
            rhel7_repo.data['repository-set'],
            rhel7_repo.data['arch'],
            version=rhel7_repo.data['releasever'],
        )
        assert session.redhatrepository.search(f'name = "{rhel7_repo_name}"', category='Enabled')
        # disable and re-enable rhel8_bos
        session.redhatrepository.disable(rhel8_repo_set_name)
        assert not session.redhatrepository.search(
            f'name = "{rhel8_repo_set_name}"', category='Enabled'
        )
        session.redhatrepository.enable(
            rhel8_repo_name,
            constants.DEFAULT_ARCHITECTURE,
            version=REPOS['rhel8_bos']['version'],
        )
        assert session.redhatrepository.search(
            f'name = "{rhel8_repo_set_name}"', category='Enabled'
        )
