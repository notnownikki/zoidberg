import logging
import paramiko
from paramiko import SSHClient
from paramiko.ssh_exception import SSHException
from Queue import Empty, Queue
from .parser import parse
from .stream import GerritEventStream


class GerritClient(SSHClient):
    def __init__(self):
        super(GerritClient, self).__init__()
        self.failed_events = []
        self.load_system_host_keys()
        self.set_missing_host_key_policy(paramiko.WarningPolicy())
        self.event_queue = Queue()
        self.event_stream = None

    def activate_ssh(self, hostname, username, port, key_filename):
        # record connection details so equality works
        self.port = port
        self.hostname = hostname
        self.username = username
        self.key_filename = key_filename

        self.connect(
            username=username, hostname=hostname, port=port,
            key_filename=key_filename)
        self.get_transport().set_keepalive(30)
        self.event_stream = GerritEventStream(self)
        self.event_stream.start()

    def store_failed_event(self, event):
        """Stores an event so it can be queued later."""
        self.failed_events.append(event)

    def enqueue_failed_events(self):
        for e in self.failed_events:
            self.event_queue.put(e)
        self.failed_events = []

    def queue_event(self, data):
        """converts the json to an object, puts it in the queue"""
        event = parse(data)
        self.event_queue.put(event)

    def get_event(self, timeout):
        try:
            return self.event_queue.get(timeout=timeout)
        except Empty:
            pass

    def is_active(self):
        transport = self.get_transport()
        return (
            self.event_stream and self.event_stream.is_active() and
            transport and transport.is_active())

    def run_command(self, command):
        gerrit_command = "gerrit " + command

        try:
            gerrit_command.encode('ascii')
        except UnicodeEncodeError:
            gerrit_command = gerrit_command.encode('utf-8')

        try:
            stdin, stdout, stderr = self.exec_command(gerrit_command,
                                                      bufsize=1,
                                                      timeout=None,
                                                      get_pty=False)
        except SSHException as err:
            logging.error("Command execution error: %s" % err)
        return stdout.readlines()

    def shutdown(self):
        self.event_stream.stop()
        self.close()
