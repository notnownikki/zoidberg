import logging
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
        self._ssh_client.key_filename = key_filename
        self.failed_events = []
        # At this point, we don't have an ssh connection active.
        # That's handled by the event processing loop, which will
        # try to activate ssh connections for a client that isn't
        # connected.

    def __eq__(self, other):
        """Two clients are equal if they have the same connection details."""
        return (
            self._ssh_client.port == other._ssh_client.port
            and
            self._ssh_client.username == other._ssh_client.username
            and
            self._ssh_client.key_filename == other._ssh_client.key_filename
            and
            self._ssh_client.hostname == other._ssh_client.hostname)

    def stop_event_stream(self):
        """Stop streaming events from `gerrit stream-events`."""
        if self._stream:
            self._stream.stop()

            # fix for bug where pygerrit's stop_event_stream would insist on
            # one more event coming from the stream before it would shut down
            self._ssh_client.close()

            self._stream.join()
            self._stream = None
            with self._events.mutex:
                self._events.queue.clear()

    def activate_ssh(self, host, username, key_filename, port=29418):
        """Activates the ssh connection."""
        self._ssh_client._connect()
        logging.info(
            'Connected to %s, gerrit version %s'
            % (host, self.gerrit_version()))

    def is_active(self):
        transport = self._ssh_client.get_transport()
        if transport and transport.is_active():
            return True
        if transport:
            self._ssh_client.connected.clear()
        return False

    def store_failed_event(self, event):
        """Stores a GerritEvent object so it can be queued later."""
        self.failed_events.append(event)

    def enqueue_failed_events(self):
        for e in self.failed_events:
            self._events.put(e)
        self.failed_events = []
