import logging
from threading import Thread, Event


class GerritEventStream(Thread):
    """
    Connects to gerrit's stream-events output and queues incoming
    data in the client.
    """
    def __init__(self, client):
        super(GerritEventStream, self).__init__()
        self._client = client
        self.daemon = True
        self._channel = None
        self._running = Event()

    def _stop_with_error(self, error_message):
        logging.error(error_message)
        self.stop()

    def is_active(self):
        return self._running.is_set()

    def run(self):
        self._running.set()
        self._channel = self._client.get_transport().open_session()
        self._channel.exec_command('gerrit stream-events')

        stdout = self._channel.makefile()
        stderr = self._channel.makefile_stderr()

        while self._running.is_set():
            try:
                if self._channel.exit_status_ready():
                    if self._channel.recv_stderr_ready():
                        error = stderr.readline().strip()
                    else:
                        error = "Remote server connection closed"
                    self._stop_with_error(error)
                else:
                    data = stdout.readline()
                    self._client.queue_event(data)
            except Exception as e:  # pylint: disable=W0703
                self._stop_with_error(repr(e))

    def stop(self):
        self._running.clear()
        if self._channel:
            self._channel.close()
