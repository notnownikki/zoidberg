from pygerrit.client import GerritClient as PyGerritClient
from pygerrit.error import GerritError
from pygerrit.ssh import (
    GerritSSHCommandResult, GerritSSHClient as PyGerritSSHClient)
from paramiko.ssh_exception import SSHException


class GerritSSHClient(PyGerritSSHClient):
    """Fixes unicode handling bug in pygerrit."""
    def run_gerrit_command(self, command):
        """ Run the given command.

        Make sure we're connected to the remote server, and run `command`.

        Return the results as a `GerritSSHCommandResult`.

        Raise `ValueError` if `command` is not a string, or `GerritError` if
        command execution fails.

        """
        if not isinstance(command, basestring):
            raise ValueError("command must be a string")
        gerrit_command = "gerrit " + command

        # fixes the unicode handling bug
        try:
            gerrit_command.encode('ascii')
        except UnicodeEncodeError:
            gerrit_command = gerrit_command.encode('utf-8')

        self._connect()
        try:
            stdin, stdout, stderr = self.exec_command(gerrit_command,
                                                      bufsize=1,
                                                      timeout=None,
                                                      get_pty=False)
        except SSHException as err:
            raise GerritError("Command execution error: %s" % err)
        return GerritSSHCommandResult(command, stdin, stdout, stderr)


class GerritClient(PyGerritClient):
    """Allows injecting of the key filename."""
    def __init__(self, host, username, key_filename, port=29418):
        super(GerritClient, self).__init__(
            host=host, username=username, port=port)
        self._ssh_client = GerritSSHClient(host, username=username, port=port)
        self._ssh_client.key_filename = key_filename
