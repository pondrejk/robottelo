"""Tests for the Docker feature.

:Requirement: Docker

:CaseAutomation: Automated

:CaseImportance: High

"""

from random import choice, randint, shuffle

from fauxfactory import gen_url
import pytest
from requests.exceptions import HTTPError

from robottelo.config import settings
from robottelo.utils.datafactory import (
    generate_strings_list,
    invalid_docker_upstream_names,
    parametrized,
    valid_docker_repository_names,
    valid_docker_upstream_names,
)

DOCKER_PROVIDER = 'Docker'


def _create_repository(module_target_sat, product, name=None, upstream_name=None):
    """Create a Docker-based repository.

    :param product: A ``Product`` object.
    :param str name: Name for the repository. If ``None`` then a random
        value will be generated.
    :param str upstream_name: A valid name of an existing upstream repository.
        If ``None`` then defaults to settings.container.upstream_name.
    :return: A ``Repository`` object.
    """
    if name is None:
        name = choice(generate_strings_list(15, ['numeric', 'html']))
    if upstream_name is None:
        upstream_name = settings.container.upstream_name
    return module_target_sat.api.Repository(
        content_type='docker',
        docker_upstream_name=upstream_name,
        name=name,
        product=product,
        url=settings.container.registry_hub,
    ).create()


@pytest.fixture
def repo(module_product, module_target_sat):
    """Create a single repository."""
    return _create_repository(module_target_sat, module_product)


@pytest.fixture
def repos(module_product, module_target_sat):
    """Create and return a list of repositories."""
    return [_create_repository(module_target_sat, module_product) for _ in range(randint(2, 5))]


@pytest.fixture
def content_view(module_org, module_target_sat):
    """Create a content view."""
    return module_target_sat.api.ContentView(composite=False, organization=module_org).create()


@pytest.fixture
def content_view_with_repo(content_view, repo):
    """Assign a docker-based repository to a content view."""
    content_view.repository = [repo]
    return content_view.update(['repository'])


@pytest.fixture
def content_view_publish_promote(content_view_with_repo, module_lce):
    """Publish and promote a new content view version into the lifecycle environment."""
    cv = content_view_with_repo
    cv.publish()

    cvv = cv.read().version[0].read()
    cvv.promote(data={'environment_ids': module_lce.id, 'force': False})

    return cv.read()


@pytest.fixture
def content_view_version(content_view_publish_promote):
    return content_view_publish_promote.version[0].read()


class TestDockerRepository:
    """Tests specific to performing CRUD methods against ``Docker``
    repositories.

    :CaseComponent: Repositories

    :team: Phoenix-content
    """

    @pytest.mark.tier1
    @pytest.mark.parametrize('name', **parametrized(valid_docker_repository_names()))
    def test_positive_create_with_name(self, module_product, name, module_target_sat):
        """Create one Docker-type repository

        :id: 3360aab2-74f3-4f6e-a083-46498ceacad2

        :parametrized: yes

        :expectedresults: A repository is created with a Docker upstream
            repository.

        :CaseImportance: Critical
        """
        repo = _create_repository(module_target_sat, module_product, name)
        assert repo.name == name
        assert repo.docker_upstream_name == settings.container.upstream_name
        assert repo.content_type == 'docker'

    @pytest.mark.tier1
    @pytest.mark.parametrize('upstream_name', **parametrized(valid_docker_upstream_names()))
    def test_positive_create_with_upstream_name(
        self, module_product, upstream_name, module_target_sat
    ):
        """Create a Docker-type repository with a valid docker upstream
        name

        :id: 742a2118-0ab2-4e63-b978-88fe9f52c034

        :parametrized: yes

        :expectedresults: A repository is created with the specified upstream
            name.

        :CaseImportance: Critical
        """
        repo = _create_repository(module_target_sat, module_product, upstream_name=upstream_name)
        assert repo.docker_upstream_name == upstream_name
        assert repo.content_type == 'docker'

    @pytest.mark.tier1
    @pytest.mark.parametrize('upstream_name', **parametrized(invalid_docker_upstream_names()))
    def test_negative_create_with_invalid_upstream_name(
        self, module_product, upstream_name, module_target_sat
    ):
        """Create a Docker-type repository with a invalid docker
        upstream name.

        :id: 2c5abb4a-e50b-427a-81d2-57eaf8f57a0f

        :parametrized: yes

        :expectedresults: A repository is not created and a proper error is
            raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            _create_repository(module_target_sat, module_product, upstream_name=upstream_name)

    @pytest.mark.tier2
    def test_positive_create_repos_using_same_product(self, module_product, module_target_sat):
        """Create multiple Docker-type repositories

        :id: 4a6929fc-5111-43ff-940c-07a754828630

        :expectedresults: Multiple docker repositories are created with a
            Docker upstream repository and they all belong to the same product.

        """
        for _ in range(randint(2, 5)):
            repo = _create_repository(module_target_sat, module_product)
            assert repo.id in [repo_.id for repo_ in module_product.read().repository]

    @pytest.mark.tier2
    def test_positive_create_repos_using_multiple_products(self, module_org, module_target_sat):
        """Create multiple Docker-type repositories on multiple products

        :id: 5a65d20b-d3b5-4bd7-9c8f-19c8af190558

        :expectedresults: Multiple docker repositories are created with a
            Docker upstream repository and they all belong to their respective
            products.

        """
        for _ in range(randint(2, 5)):
            product = module_target_sat.api.Product(organization=module_org).create()
            for _ in range(randint(2, 3)):
                repo = _create_repository(module_target_sat, product)
                product = product.read()
                assert repo.id in [repo_.id for repo_ in product.repository]

    @pytest.mark.tier1
    @pytest.mark.parametrize('new_name', **parametrized(valid_docker_repository_names()))
    def test_positive_update_name(self, repo, new_name):
        """Create a Docker-type repository and update its name.

        :id: 7967e6b5-c206-4ad0-bcf5-64a7ce85233b

        :parametrized: yes

        :expectedresults: A repository is created with a Docker upstream
            repository and that its name can be updated.

        :CaseImportance: Critical
        """
        repo.name = new_name
        repo = repo.update()
        assert repo.name == new_name

    @pytest.mark.tier1
    def test_positive_update_upstream_name(self, repo):
        """Create a Docker-type repository and update its upstream name.

        :id: 4e2fb78d-0b6a-4455-8869-8eaf9d4a61b0

        :expectedresults: A repository is created with a Docker upstream
            repository and that its upstream name can be updated.

        :CaseImportance: Critical
        """
        assert repo.docker_upstream_name == settings.container.upstream_name

        # Update the repository upstream name
        new_upstream_name = 'fedora/ssh'
        repo.docker_upstream_name = new_upstream_name
        repo = repo.update()
        assert repo.docker_upstream_name == new_upstream_name

    @pytest.mark.tier2
    def test_positive_update_url(self, repo):
        """Create a Docker-type repository and update its URL.

        :id: 6a588e65-bf1d-4ca9-82ce-591f9070215f

        :expectedresults: A repository is created with a Docker upstream
            repository and that its URL can be updated.

        :BZ: 1489322
        """
        assert repo.url == settings.container.registry_hub

        # Update the repository URL
        new_url = gen_url()
        repo.url = new_url
        repo = repo.update()
        assert repo.url == new_url
        assert repo.url != settings.container.registry_hub

    @pytest.mark.tier1
    def test_positive_delete(self, repo):
        """Create and delete a Docker-type repository

        :id: 92df93cb-9de2-40fa-8451-b8c1ba8f45be

        :expectedresults: A repository is created with a Docker upstream
            repository and then deleted.

        :CaseImportance: Critical
        """
        # Delete it
        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()

    @pytest.mark.tier2
    def test_positive_delete_random_repo(self, module_org, module_target_sat):
        """Create Docker-type repositories on multiple products and
        delete a random repository from a random product.

        :id: cbc2792d-cf81-41f7-8889-001a27e4dd66

        :expectedresults: Random repository can be deleted from random product
            without altering the other products.
        """
        repos = []
        products = [
            module_target_sat.api.Product(organization=module_org).create()
            for _ in range(randint(2, 5))
        ]
        for product in products:
            repo = _create_repository(module_target_sat, product)
            assert repo.content_type == 'docker'
            repos.append(repo)

        # Delete a random repository
        shuffle(repos)
        repo = repos.pop()
        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()

        # Check if others repositories are not touched
        for repo in repos:
            repo = repo.read()
            assert repo.product.id in [prod.id for prod in products]


class TestDockerContentView:
    """Tests specific to using ``Docker`` repositories with Content Views.

    :CaseComponent: ContentViews

    :team: Phoenix-content
    """

    @pytest.mark.tier2
    def test_positive_add_synced_docker_repo(self, module_org, module_product, module_target_sat):
        """Create and sync a Docker-type repository

        :id: 3c7d6f17-266e-43d3-99f8-13bf0251eca6

        :expectedresults: A repository is created with a Docker repository and
            it is synchronized.
        """
        repo = _create_repository(module_target_sat, module_product)
        repo.sync(timeout=600)
        repo = repo.read()
        assert repo.content_counts['docker_manifest'] > 0

        # Create content view and associate docker repo
        content_view = module_target_sat.api.ContentView(
            composite=False, organization=module_org
        ).create()
        content_view.repository = [repo]
        content_view = content_view.update(['repository'])
        assert repo.id in [repo_.id for repo_ in content_view.repository]

    @pytest.mark.tier2
    def test_positive_add_docker_repos_to_ccv(self, module_org, module_target_sat):
        """Add multiple Docker-type repositories to a composite
        content view.

        :id: 3824ccae-fb59-4f63-a1ab-a4f2419fcadd

        :expectedresults: One repository is created with a Docker upstream
            repository and the product is added to a random number of content
            views which are then added to a composite content view.
        """
        cv_versions = []
        product = module_target_sat.api.Product(organization=module_org).create()
        for _ in range(randint(2, 5)):
            # Create content view and associate docker repo
            content_view = module_target_sat.api.ContentView(
                composite=False, organization=module_org
            ).create()
            repo = _create_repository(module_target_sat, product)
            content_view.repository = [repo]
            content_view = content_view.update(['repository'])
            assert repo.id in [repo_.id for repo_ in content_view.repository]

            # Publish it and grab its version ID (there should be one version)
            content_view.publish()
            content_view = content_view.read()
            cv_versions.append(content_view.version[0])

        # Create composite content view and associate content view to it
        comp_content_view = module_target_sat.api.ContentView(
            composite=True, organization=module_org
        ).create()
        for cv_version in cv_versions:
            comp_content_view.component.append(cv_version)
            comp_content_view = comp_content_view.update(['component'])
            assert cv_version.id in [component.id for component in comp_content_view.component]

    @pytest.mark.tier2
    def test_positive_publish_with_docker_repo_composite(self, module_org, module_target_sat):
        """Add Docker-type repository to composite content view and
        publish it once.

        :id: 103ebee0-1978-4fc5-a11e-4dcdbf704185

        :expectedresults: One repository is created with an upstream repository
            and the product is added to a content view which is then published
            only once and then added to a composite content view which is also
            published only once.

        :BZ: 1217635
        """
        repo = _create_repository(
            module_target_sat, module_target_sat.api.Product(organization=module_org).create()
        )
        content_view = module_target_sat.api.ContentView(
            composite=False, organization=module_org
        ).create()
        content_view.repository = [repo]
        content_view = content_view.update(['repository'])
        assert repo.id in [repo_.id for repo_ in content_view.repository]

        # Not published yet?
        content_view = content_view.read()
        assert content_view.last_published is None
        assert float(content_view.next_version) == 1.0

        # Publish it and check that it was indeed published.
        content_view.publish()
        content_view = content_view.read()
        assert content_view.last_published is not None
        assert float(content_view.next_version) > 1.0

        # Create composite content view…
        comp_content_view = module_target_sat.api.ContentView(
            composite=True, organization=module_org
        ).create()
        comp_content_view.component = [content_view.version[0]]
        comp_content_view = comp_content_view.update(['component'])
        assert content_view.version[0].id in [
            component.id for component in comp_content_view.component
        ]
        # … publish it…
        comp_content_view.publish()
        # … and check that it was indeed published
        comp_content_view = comp_content_view.read()
        assert comp_content_view.last_published is not None
        assert float(comp_content_view.next_version) > 1.0

    @pytest.mark.tier2
    def test_positive_promote_multiple_with_docker_repo(self, module_org, module_target_sat):
        """Add Docker-type repository to content view and publish it.
        Then promote it to multiple available lifecycle-environments.

        :id: 7b0cbc95-5f63-47f3-9048-e6917078be73

        :expectedresults: Docker-type repository is promoted to content view
            found in the specific lifecycle-environments.
        """
        repo = _create_repository(
            module_target_sat, module_target_sat.api.Product(organization=module_org).create()
        )

        content_view = module_target_sat.api.ContentView(
            composite=False, organization=module_org
        ).create()
        content_view.repository = [repo]
        content_view = content_view.update(['repository'])
        assert [repo.id] == [repo_.id for repo_ in content_view.repository]

        content_view.publish()
        cvv = content_view.read().version[0]
        assert len(cvv.read().environment) == 1

        for i in range(1, randint(3, 6)):
            lce = module_target_sat.api.LifecycleEnvironment(organization=module_org).create()
            cvv.promote(data={'environment_ids': lce.id, 'force': False})
            assert len(cvv.read().environment) == i + 1

    @pytest.mark.upgrade
    @pytest.mark.tier2
    def test_positive_promote_multiple_with_docker_repo_composite(
        self, module_org, module_target_sat
    ):
        """Add Docker-type repository to content view and publish it.
        Then add that content view to composite one. Publish and promote that
        composite content view to the multiple available lifecycle-environments

        :id: 91ac0f4a-8974-47e2-a1d6-7d734aa4ad46

        :expectedresults: Docker-type repository is promoted to content view
            found in the specific lifecycle-environments.
        """
        repo = _create_repository(
            module_target_sat, module_target_sat.api.Product(organization=module_org).create()
        )
        content_view = module_target_sat.api.ContentView(
            composite=False, organization=module_org
        ).create()
        content_view.repository = [repo]
        content_view = content_view.update(['repository'])
        assert [repo.id] == [repo_.id for repo_ in content_view.repository]

        content_view.publish()
        cvv = content_view.read().version[0].read()

        comp_content_view = module_target_sat.api.ContentView(
            composite=True, organization=module_org
        ).create()
        comp_content_view.component = [cvv]
        comp_content_view = comp_content_view.update(['component'])
        assert cvv.id == comp_content_view.component[0].id

        comp_content_view.publish()
        comp_cvv = comp_content_view.read().version[0]
        assert len(comp_cvv.read().environment) == 1

        for i in range(1, randint(3, 6)):
            lce = module_target_sat.api.LifecycleEnvironment(organization=module_org).create()
            comp_cvv.promote(data={'environment_ids': lce.id, 'force': False})
            assert len(comp_cvv.read().environment) == i + 1


class TestDockerActivationKey:
    """Tests specific to adding ``Docker`` repositories to Activation Keys.

    :CaseComponent: ActivationKeys

    :team: Phoenix-subscriptions
    """

    @pytest.mark.tier2
    def test_positive_add_docker_repo_cv(
        self, module_lce, module_org, repo, content_view_publish_promote, module_target_sat
    ):
        """Add Docker-type repository to a non-composite content view
        and publish it. Then create an activation key and associate it with the
        Docker content view.

        :id: ce4ae928-49c7-4782-a032-08885050dd83

        :expectedresults: Docker-based content view can be added to activation
            key
        """
        content_view = content_view_publish_promote
        ak = module_target_sat.api.ActivationKey(
            content_view=content_view, environment=module_lce, organization=module_org
        ).create()
        assert ak.content_view.id == content_view.id
        assert ak.content_view.read().repository[0].id == repo.id

    @pytest.mark.tier2
    def test_positive_remove_docker_repo_cv(
        self, module_org, module_lce, content_view_publish_promote, module_target_sat
    ):
        """Create an activation key and associate it with the Docker content view. Then remove
        this content view from the activation key.

        :id: 6a887a67-6700-47ac-9230-deaa0e382f22

        :expectedresults: Docker-based content view can be added and then
            removed from the activation key.

        """
        content_view = content_view_publish_promote
        ak = module_target_sat.api.ActivationKey(
            content_view=content_view, environment=module_lce, organization=module_org
        ).create()
        assert ak.content_view.id == content_view.id
        ak.content_view = None
        assert ak.update(['content_view']).content_view is None

    @pytest.mark.tier2
    def test_positive_add_docker_repo_ccv(
        self, content_view_version, module_lce, module_org, module_target_sat
    ):
        """Add Docker-type repository to a non-composite content view and
        publish it. Then add this content view to a composite content view and
        publish it. Create an activation key and associate it with the
        composite Docker content view.

        :id: 2fc8a462-9d91-48bc-8e32-7ff8f769b9e4

        :expectedresults: Docker-based content view can be added to activation
            key
        """
        cvv = content_view_version
        comp_content_view = module_target_sat.api.ContentView(
            composite=True, organization=module_org
        ).create()
        comp_content_view.component = [cvv]
        comp_content_view = comp_content_view.update(['component'])
        assert cvv.id == comp_content_view.component[0].id

        comp_content_view.publish()
        comp_cvv = comp_content_view.read().version[0].read()
        comp_cvv.promote(data={'environment_ids': module_lce.id, 'force': False})

        ak = module_target_sat.api.ActivationKey(
            content_view=comp_content_view, environment=module_lce, organization=module_org
        ).create()
        assert ak.content_view.id == comp_content_view.id

    @pytest.mark.tier2
    def test_positive_remove_docker_repo_ccv(
        self, module_lce, module_org, content_view_version, module_target_sat
    ):
        """Add Docker-type repository to a non-composite content view
        and publish it. Then add this content view to a composite content view
        and publish it. Create an activation key and associate it with the
        composite Docker content view. Then, remove the composite content view
        from the activation key.

        :id: f3542272-13db-4a49-bc27-d1137172df41

        :expectedresults: Docker-based composite content view can be added and
            then removed from the activation key.
        """
        cvv = content_view_version
        comp_content_view = module_target_sat.api.ContentView(
            composite=True, organization=module_org
        ).create()
        comp_content_view.component = [cvv]
        comp_content_view = comp_content_view.update(['component'])
        assert cvv.id == comp_content_view.component[0].id

        comp_content_view.publish()
        comp_cvv = comp_content_view.read().version[0].read()
        comp_cvv.promote(data={'environment_ids': module_lce.id, 'force': False})

        ak = module_target_sat.api.ActivationKey(
            content_view=comp_content_view, environment=module_lce, organization=module_org
        ).create()
        assert ak.content_view.id == comp_content_view.id
        ak.content_view = None
        assert ak.update(['content_view']).content_view is None
