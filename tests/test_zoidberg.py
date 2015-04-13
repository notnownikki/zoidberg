import logging
import testtools
from mock import ANY, Mock, patch
from weakref import WeakKeyDictionary
from zoidberg.zoidberg import Zoidberg # woop woop woop
from zoidberg import actions


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

    @patch.object(TestableZoidberg, 'load_config')
    @patch.object(TestableZoidberg, 'config_file_has_changed')
    @patch.object(TestableZoidberg, 'enqueue_failed_events')
    @patch.object(TestableZoidberg, 'process_event')
    @patch.object(TestableZoidberg, 'get_event')
    @patch.object(TestableZoidberg ,'process_startup_tasks')
    def test_process_loop_handles_config_exceptions(
            self, mock_pst, mock_get_event, mock_process_event,
            mock_enqueue_failed_events, mock_config_file_has_changed,
            mock_load_config):
        """
        When reloading the config, if there is an exception, it should
        not crash the process.
        """
        self._setup_process_loop(1)
        mock_get_event.return_value = False
        mock_config_file_has_changed.return_value = True
        mock_load_config.side_effect = Exception('Bad news, everybody!')
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


# TODO: connect_client
# TODO: validate_actions
# TODO: process_event
# TODO: get_client
# TODO: load_config
# TODO: run_action
# TODO: Action#validate_config