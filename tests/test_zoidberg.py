import logging
import os
import pygerrit
import testtools
import yaml
from mock import ANY, Mock, patch
from weakref import WeakKeyDictionary
from zoidberg.zoidberg import Zoidberg # woop woop woop
from zoidberg import actions
from zoidberg import configuration


class CountdownToFalse(object):
    """A descriptor that counts down until it returns False"""
    def __init__(self, default):
        self.default = default
        self.data = WeakKeyDictionary()
        
    def __get__(self, instance, owner):
        countdown = self.data.get(instance, self.default)
        if countdown > 0:
            countdown -= 1
            self.data[instance] = countdown
            return True
        return False
    
    def __set__(self, instance, value):
        if not value:
            # make sure we're False
            self.data[instance] = 0
            return

        self.data[instance] = value


class TestableZoidberg(Zoidberg):
    running = CountdownToFalse(1)


class ZoidbergTestCase(testtools.TestCase):
    def setUp(self):
        super(ZoidbergTestCase, self).setUp()
        self.zoidberg = TestableZoidberg('./tests/etc/zoidberg.yaml')

    def _setup_process_loop(self, run_times=1):
        # only run the inner loop in process_loop run_times
        self.zoidberg.running = run_times

    @patch.object(TestableZoidberg, 'load_config')
    @patch.object(TestableZoidberg, 'config_file_has_changed')
    @patch.object(TestableZoidberg, 'enqueue_failed_events')
    @patch.object(TestableZoidberg, 'process_event')
    @patch.object(TestableZoidberg, 'get_event')
    @patch.object(TestableZoidberg ,'process_startup_tasks')
    def test_process_loop_startup_tasks(
            self, mock_pst, mock_get_event, mock_process_event,
            mock_enqueue_failed_events, mock_config_file_has_changed,
            mock_load_config):
        """
        Check the process loop calls process_startup_tasks
        once per loop.
        """
        self._setup_process_loop(2)
        mock_get_event.return_value = False
        self.zoidberg.process_loop()
        self.assertEqual(2, mock_pst.call_count)

    @patch.object(TestableZoidberg, 'load_config')
    @patch.object(TestableZoidberg, 'config_file_has_changed')
    @patch.object(TestableZoidberg, 'enqueue_failed_events')
    @patch.object(TestableZoidberg, 'process_event')
    @patch.object(TestableZoidberg, 'get_event')
    @patch.object(TestableZoidberg ,'process_startup_tasks')
    def test_process_loop_enqueues_failed_events(
            self, mock_pst, mock_get_event, mock_process_event,
            mock_enqueue_failed_events, mock_config_file_has_changed,
            mock_load_config):
        """
        Each processing loop should pass each gerrit config to
        enqueue_failed_events.
        """
        self._setup_process_loop(1)
        mock_get_event.return_value = False
        self.zoidberg.process_loop()
        mock_enqueue_failed_events.assert_any_call(
            self.zoidberg.config.gerrits['master'])
        mock_enqueue_failed_events.assert_any_call(
            self.zoidberg.config.gerrits['thirdparty'])
        self.assertEqual(2, mock_enqueue_failed_events.call_count)

    @patch.object(TestableZoidberg, 'load_config')
    @patch.object(TestableZoidberg, 'config_file_has_changed')
    @patch.object(TestableZoidberg, 'enqueue_failed_events')
    @patch.object(TestableZoidberg, 'process_event')
    @patch.object(TestableZoidberg, 'get_event')
    @patch.object(TestableZoidberg ,'process_startup_tasks')
    def test_process_loop_get_event_passed_to_process_event(
            self, mock_pst, mock_get_event, mock_process_event,
            mock_enqueue_failed_events, mock_config_file_has_changed,
            mock_load_config):
        """
        Each processing loop should get an event for the gerrit
        and if an event is returned, pass it to process_event.
        """
        self._setup_process_loop(1)
        mock_get_event.side_effect = ['Event', False, False]
        self.zoidberg.process_loop()
        mock_get_event.assert_any_call(
            self.zoidberg.config.gerrits['master'], timeout=ANY)
        mock_get_event.assert_any_call(
            self.zoidberg.config.gerrits['thirdparty'], timeout=ANY)
        mock_process_event.assert_called_once_with(
            'Event', self.zoidberg.config.gerrits['master'])

    @patch.object(TestableZoidberg, 'load_config')
    @patch.object(TestableZoidberg, 'config_file_has_changed')
    @patch.object(TestableZoidberg, 'enqueue_failed_events')
    @patch.object(TestableZoidberg, 'process_event')
    @patch.object(TestableZoidberg, 'get_event')
    @patch.object(TestableZoidberg ,'process_startup_tasks')
    def test_process_loop_triggers_config_reload(
            self, mock_pst, mock_get_event, mock_process_event,
            mock_enqueue_failed_events, mock_config_file_has_changed,
            mock_load_config):
        """
        The process loop should check if the config file has
        changed, and if it has, trigger a config reload.
        """
        self._setup_process_loop(1)
        mock_get_event.return_value = False
        mock_config_file_has_changed.return_value = True
        self.zoidberg.process_loop()
        mock_load_config.assert_called_once_with('./tests/etc/zoidberg.yaml')

    def test_queue_startup_tasks(self):
        """
        Gerrit configurations that have startup tasks should
        get them queued in self.startup_tasks.
        """
        gerrit_config = self.zoidberg.config.gerrits['master']
        self.zoidberg.queue_startup_tasks(gerrit_config)
        self.assertEqual(1, self.zoidberg.startup_tasks.qsize())
        task = self.zoidberg.startup_tasks.get()
        self.assertEqual(
            {'task': gerrit_config['startup'][0], 'source': gerrit_config},
            task)

    @patch.object(actions.SyncBranchAction, 'startup')
    def test_process_startup_tasks(self, mock_startup):
        """
        Queued startup tasks should have their action instantiated
        and startup called.
        """
        gerrit_config = self.zoidberg.config.gerrits['master']
        task = gerrit_config['startup'][0]
        mock_startup.return_value = True
        self.zoidberg.queue_startup_tasks(gerrit_config)
        self.zoidberg.process_startup_tasks()
        mock_startup.assert_called_once_with(
            self.zoidberg.config, task, gerrit_config)
        self.assertEqual(
            0,
            self.zoidberg.startup_tasks.qsize())

    @patch.object(actions.SyncBranchAction, 'startup')
    def test_process_startup_tasks_requeues_failed(self, mock_startup):
        """
        Queued startup tasks that fail to run should be requeued.
        """
        gerrit_config = self.zoidberg.config.gerrits['master']
        task = gerrit_config['startup'][0]
        mock_startup.return_value = False
        self.zoidberg.queue_startup_tasks(gerrit_config)
        self.zoidberg.process_startup_tasks()
        self.assertEqual(
            1,
            self.zoidberg.startup_tasks.qsize())
        self.assertEqual(
            {'task': task, 'source': gerrit_config},
            self.zoidberg.startup_tasks.get())

    @patch.object(TestableZoidberg ,'queue_startup_tasks')
    def test_connect_client(self, mock_queue_startup_tasks):
        """
        connect_client should use the details in a gerrit config
        block to activate the ssh client, start the gerrit event
        stream, and queue startup tasks, if the client if not
        already active.
        """
        gerrit_cfg = self.zoidberg.config.gerrits['master']
        mock_client = Mock()
        gerrit_cfg['client'] = mock_client
        mock_client.is_active.return_value = False
        self.zoidberg.connect_client(gerrit_cfg)
        mock_client.activate_ssh.assert_called_once_with(
            gerrit_cfg['host'], gerrit_cfg['username'],
            gerrit_cfg['key_filename'], 29418)
        self.assertEqual(1, mock_client.start_event_stream.call_count)
        mock_queue_startup_tasks.assert_called_once_with(gerrit_cfg)

    @patch.object(TestableZoidberg ,'queue_startup_tasks')
    def test_connect_client_already_active(self, mock_queue_startup_tasks):
        """
        connect_client should not make any calls on the client to activate
        it, if it's already active.
        """
        gerrit_cfg = self.zoidberg.config.gerrits['master']
        mock_client = Mock()
        gerrit_cfg['client'] = mock_client
        mock_client.is_active.return_value = True
        self.zoidberg.connect_client(gerrit_cfg)
        self.assertEqual(0, mock_client.activate_ssh.call_count)
        self.assertEqual(0, mock_client.start_event_stream.call_count)
        self.assertEqual(0, mock_queue_startup_tasks.call_count)

    @patch.object(TestableZoidberg ,'queue_startup_tasks')
    def test_connect_client_pygerrit_error(self, mock_queue_startup_tasks):
        """
        pygerrit will raise an exception if the ssh client fails to
        connect, that should be silently discarded by connect_client
        so that we can try again next time we try to connect_client.
        """
        gerrit_cfg = self.zoidberg.config.gerrits['master']
        mock_client = Mock()
        gerrit_cfg['client'] = mock_client
        mock_client.is_active.return_value = False
        mock_client.activate_ssh.side_effect = pygerrit.error.GerritError(
            'SSH Connnection Failed')
        self.zoidberg.connect_client(gerrit_cfg)
        self.assertEqual(1, mock_client.activate_ssh.call_count)
        self.assertEqual(0, mock_client.start_event_stream.call_count)
        self.assertEqual(0, mock_queue_startup_tasks.call_count)

    def test_invalid_configurations(self):
        """
        Check each of the invalid configurations does not got loaded and
        replace the existing configuration.
        """
        invalid_dir = './tests/etc/invalid/'
        configs = os.listdir(invalid_dir)
        existing_config = self.zoidberg.config
        for config_file in configs:
            self.zoidberg.load_config(
                os.path.join(invalid_dir, config_file))
            self.assertEqual(
                existing_config, self.zoidberg.config, config_file)

    @patch.object(TestableZoidberg, 'connect_client')
    def test_get_client_connects_client_if_not_active(
            self, mock_connect_client):
        """If the client is not active, have connect_client connect it."""
        mock_client = Mock()
        gerrit_cfg = self.zoidberg.config.gerrits['master']
        gerrit_cfg['client'] = mock_client
        mock_client.is_active.return_value = False
        self.zoidberg.get_client(gerrit_cfg)
        self.assertEqual(1, mock_client.is_active.call_count)
        mock_connect_client.assert_called_once_with(gerrit_cfg)

    def test_plugins_loaded(self):
        """
        Plugins listed in the configuration have their actions registered.
        """
        action = actions.ActionRegistry.get(
            'thirdpartyactions.AnExcellentAction')
        self.assertTrue(issubclass(action, actions.Action))
        action = actions.ActionRegistry.get(
            'moreactions.JustSomeActionOrOther')
        self.assertTrue(issubclass(action, actions.Action))
