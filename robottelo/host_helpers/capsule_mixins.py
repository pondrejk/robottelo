from datetime import UTC, datetime, timedelta
import time

from box import Box
from dateutil.parser import parse

from robottelo import ssh
from robottelo.config import settings
from robottelo.constants import (
    PULP_ARTIFACT_DIR,
    PUPPET_CAPSULE_INSTALLER,
    PUPPET_COMMON_INSTALLER_OPTS,
)
from robottelo.enums import NetworkType
from robottelo.logging import logger
from robottelo.utils.installer import InstallerCommand


class EnablePluginsCapsule:
    """Miscellaneous settings helper methods"""

    def enable_puppet_capsule(self, satellite=None):
        # Set Satellite URL for puppet-server-foreman-url
        if satellite is not None:
            satellite_url = f'https://{satellite.hostname}'
            PUPPET_COMMON_INSTALLER_OPTS['puppet-server-foreman-url'] = satellite_url
        enable_capsule_cmd = InstallerCommand(
            installer_args=PUPPET_CAPSULE_INSTALLER, installer_opts=PUPPET_COMMON_INSTALLER_OPTS
        )
        result = self.execute(enable_capsule_cmd.get_command(), timeout='20m')
        assert result.status == 0
        assert 'Success!' in result.stdout
        return self


class CapsuleInfo:
    """Miscellaneous Capsule helper methods"""

    def wait_for_tasks(
        self,
        search_query,
        search_rate=1,
        max_tries=10,
        poll_rate=None,
        poll_timeout=None,
        must_succeed=True,
    ):
        """Search for tasks by specified search query and poll them to ensure that
        task has finished.

        :param search_query: Search query that will be passed to API call.
        :param search_rate: Delay between searches.
        :param max_tries: How many times search should be executed.
        :param poll_rate: Delay between the end of one task check-up and
            the start of the next check-up. Parameter for ``sat.api.ForemanTask.poll()`` method.
        :param poll_timeout: Maximum number of seconds to wait until timing out.
            Parameter for ``sat.api.ForemanTask.poll()`` method.
        :param must_succeed: Assert success result on finished task.
        :return: List of ``sat.api.ForemanTask`` entities.
        :raises: ``AssertionError``. If not tasks were found until timeout.
        """
        for _ in range(max_tries):
            tasks = self.satellite.api.ForemanTask().search(query={'search': search_query})
            if tasks:
                for task in tasks:
                    task.poll(poll_rate=poll_rate, timeout=poll_timeout, must_succeed=must_succeed)
                break
            time.sleep(search_rate)
        else:
            raise AssertionError(f"No task was found using query '{search_query}'")
        return tasks

    def wait_for_sync(self, start_time=None, timeout=600):
        """Wait for capsule sync to finish and assert success.
        Assert that a task to sync lifecycle environment to the
        capsule is started (or finished already), and succeeded.
        :raises: ``AssertionError``: If a capsule sync verification fails based on the conditions.

        - Found some active sync task(s) for capsule, or it just finished (recent sync time).
        - Any active sync task(s) polled, succeeded, and the capsule last_sync_time is updated.
        - last_sync_time after final task is on or newer than start_time.
        - The total sync time duration (seconds) is within timeout and not negative.

        :param start_time: (datetime): UTC time to compare against capsule's last_sync_time.
            Default: None (current UTC).
        :param timeout: (int) maximum seconds for active task(s) and queries to finish.

        :return:
            list of polled finished tasks that were in-progress from `active_sync_tasks`.
        """
        # Fetch initial capsule sync status
        logger.info(f"Waiting for capsule {self.hostname} sync to finish ...")
        sync_status = self.nailgun_capsule.content_get_sync(timeout=timeout, synchronous=True)
        # Current UTC time for start_time, if not provided
        if start_time is None:
            start_time = datetime.now(UTC).replace(microsecond=0)
        # 1s margin of safety for rounding
        start_time = (
            (start_time - timedelta(seconds=1))
            .replace(microsecond=0)
            .strftime('%Y-%m-%d %H:%M:%S UTC')
        )
        # Assert presence of recent sync activity:
        #   one or more ongoing sync tasks for the capsule,
        #   Or, capsule's last_sync_time is on or after start_time
        assert len(sync_status['active_sync_tasks']) or (
            parse(sync_status['last_sync_time']) >= parse(start_time)
        ), (
            f"No active or recent sync found for capsule {self.hostname}."
            f" `active_sync_tasks` was empty: {sync_status['active_sync_tasks']},"
            f" and the `last_sync_time`: {sync_status['last_sync_time']},"
            f" was prior to the `start_time`: {start_time}."
        )
        sync_tasks = []
        # Poll and verify succeeds, any active sync task from initial status.
        logger.info(f"Active tasks: {sync_status['active_sync_tasks']}")
        for task in sync_status['active_sync_tasks']:
            sync_tasks.append(self.satellite.api.ForemanTask(id=task['id']).poll(timeout=timeout))
            logger.info(f"Active sync task :id {task['id']} succeeded.")

        # Fetch updated capsule status (expect no ongoing sync)
        logger.info(f"Querying updated sync status from capsule {self.hostname}.")
        updated_status = self.nailgun_capsule.content_get_sync(timeout=timeout, synchronous=True)
        # Last sync task end time is the same as capsule's last sync time.
        assert parse(updated_status['last_sync_time']) == parse(
            updated_status['last_sync_task']['ended_at']
        ), f"`last_sync_time` does not match final task's end time. Capsule: {self.hostname}"

        # Total time taken is not negative (sync prior to start_time),
        # and did not exceed timeout.
        assert (
            timedelta(seconds=0)
            <= parse(updated_status['last_sync_time']) - parse(start_time)
            <= timedelta(seconds=timeout)
        ), (
            f"No recent sync task(s) were found for capsule: {self.hostname}, or task(s) timed out."
            f" `last_sync_time`: ({updated_status['last_sync_time']}) was prior to `start_time`: ({start_time})"
            f" or exceeded timeout ({timeout}s)."
        )
        # No failed or active tasks remaining
        assert len(updated_status['last_failed_sync_tasks']) == 0
        assert len(updated_status['active_sync_tasks']) == 0

        # return any polled sync tasks, that were initially in-progress
        return sync_tasks

    def get_published_repo_url(self, org, prod, repo, lce=None, cv=None):
        """Forms url of a repo or CV published on a Satellite or Capsule.

        :param str org: organization label
        :param str prod: product label
        :param str repo: repository label
        :param str lce: lifecycle environment label
        :param str cv: content view label
        :return: url of the specific repo or CV
        """
        if lce and cv:
            return f'{self.url}/pulp/content/{org}/{lce}/{cv}/custom/{prod}/{repo}/'
        return f'{self.url}/pulp/content/{org}/Library/custom/{prod}/{repo}/'

    def get_artifacts(self, since=None):
        """Get paths of pulp artifact.

        :param str since: Creation time of artifact we are looking for.
        :return: A list of artifacts paths.
        """
        query = f'find {PULP_ARTIFACT_DIR} -type f'
        if since:
            query = f'{query} -newermt "{since}"'
        return self.execute(query).stdout.splitlines()

    def get_artifact_info(self, checksum=None, path=None):
        """Returns information about pulp artifact if found on FS,
        throws FileNotFoundError otherwise.

        :param checksum: Checksum of the artifact to look for.
        :param path: Path to the artifact.
        :return: A Box with artifact path, size, latest sum and info.
        """
        if not (checksum or path):
            raise ValueError('Either checksum or path must be specified')

        if not path:
            path = f'{PULP_ARTIFACT_DIR}{checksum[0:2]}/{checksum[2:]}'

        res = self.execute(f'stat --format %s {path}')
        if res.status:
            raise FileNotFoundError(f'Artifact not found: {path}')
        size = int(res.stdout)
        real_sum = self.execute(f'sha256sum {path}').stdout.split()[0]
        info = self.execute(f'file {path}').stdout.strip().split(': ')[1]

        return Box(path=path, size=size, sum=real_sum, info=info)

    def cutoff_host_setup_log(self, proxy_hostname, hostname):
        """For testing of HTTP Proxy, disable direct connection to some host using firewall. On the Proxy, setup logs for later comparison that the Proxy was used."""
        log_path = '/var/log/squid/access.log'
        old_log = ssh.command('echo /tmp/$RANDOM').stdout.strip()
        ssh.command(
            f'sshpass -p "{settings.server.ssh_password}" scp -o StrictHostKeyChecking=no root@{proxy_hostname}:{log_path} {old_log}'
        )
        # make sure the system can't communicate with the git directly, without proxy
        result = self.execute(f'dig +short AAAA {hostname}').stdout.strip()
        if len(result) > 0:
            assert (
                self.execute(
                    f'firewall-cmd --permanent --direct --add-rule ipv6 filter OUTPUT 1 -d {result} -j REJECT && firewall-cmd --reload'
                ).status
                == 0
            )
        result = self.execute(f'dig +short A {hostname}').stdout.strip()
        if len(result) > 0:
            assert (
                self.execute(
                    f'firewall-cmd --permanent --direct --add-rule ipv4 filter OUTPUT 1 -d {result} -j REJECT && firewall-cmd --reload'
                ).status
                == 0
            )
        assert self.execute(f'ping -c 2 {hostname}').status != 0, (
            "the connection was not successfully disabled"
        )
        return old_log

    def restore_host_check_log(self, proxy_hostname, hostname, old_log):
        """For testing of HTTP Proxy, call after running the thing that should use Proxy."""
        log_path = '/var/log/squid/access.log'
        result = self.execute(f'dig +short AAAA {hostname}').stdout.strip()
        if len(result) > 0:
            self.execute(
                f'firewall-cmd --permanent --direct --remove-rule ipv6 filter OUTPUT 1 -d {result} -j REJECT && firewall-cmd --reload'
            )
        result = self.execute(f'dig +short A {hostname}').stdout.strip()
        if len(result) > 0:
            self.execute(
                f'firewall-cmd --permanent --direct --remove-rule ipv4 filter OUTPUT 1 -d {result} -j REJECT && firewall-cmd --reload'
            )

        new_log = ssh.command('echo /tmp/$RANDOM').stdout.strip()
        ssh.command(
            f'sshpass -p "{settings.server.ssh_password}" scp -o StrictHostKeyChecking=no root@{proxy_hostname}:{log_path} {new_log}'
        )
        diff = ssh.command(f'diff {old_log} {new_log}').stdout
        satellite_ip = ssh.command(
            f'dig {"AAAA" if settings.server.network_type == NetworkType.IPV6 else "A"} +short $(hostname)'
        ).stdout.strip()
        # assert that proxy has been used
        assert satellite_ip in diff
