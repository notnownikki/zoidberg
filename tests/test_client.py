from mock import Mock, patch
import paramiko
import threading
import socket
import StringIO
import testtools
from zoidberg import gerrit
from zoidberg import stream


class ClientTestCase(testtools.TestCase):
    def test_queue_event(self):
        """
        When a JSON representation of an event is passed to
        queue_event, a python object ends up in the queue.
        """
        client = gerrit.GerritClient()
        json_event = '{"type": "orsm-event", "something": "value"}'
        client.queue_event(json_event)
        event = client.event_queue.get(timeout=0.1)
        self.assertEqual('orsm-event', event.type)
        self.assertEqual('value', event.something)

    def test_stream_supplies_client_with_events(self):
        """
        When a stream runs, it should do the following:
        * get the transport from the client
        * open a new session from the transport
        * read in new event data
        * send that event data to the client
        """
        mock_transport = Mock()
        mock_channel = Mock()
        mock_event = Mock()
        stream_data_io = StringIO.StringIO(
            '{"type": "orsm-event", "something": "value"}')
        client = Mock()

        client.get_transport.side_effect = [mock_transport]
        mock_transport.open_session.side_effect = [mock_channel]
        mock_channel.exit_status_ready.side_effect = [False]
        mock_channel.makefile.side_effect = [stream_data_io]
        mock_event.is_set.side_effect = [True, False]

        stream = gerrit.GerritEventStream(client)
        stream._running = mock_event
        stream.run()
        mock_channel.exec_command.assert_called_once_with(
            'gerrit stream-events')
        client.queue_event.assert_called_once_with(
            '{"type": "orsm-event", "something": "value"}')
