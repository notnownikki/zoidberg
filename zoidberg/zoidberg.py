#                                            xmHTTTTT%ms.
#    _____________________                   z?!!!!!!!!!!!!!!?m
#   /                     \                z!!!!!!!!!!!!!!!!!!!!%
#   | Zoidberg, a tool for \            eHT!!!!!!!!!!!!!!!!!!!!!!!L
#   |  gerrit instances to |           M!!!!!!!!!!!!!!!!!!!!!!!!!!!>
#   |  interact with each  |        z!!!!!!!!!!XH!!!!!!!!!!!!!!!!!!X
#   |   other, why not!   /         "$$F*tX!!W?!!!!!!!!!!!!!!!!!!!!!
#    \ ________________  /          >     M!!!   4$$NX!!!!!!!!!!!!!t
#                      \ \          tmem?!!!!?    ""   "X!!!!!!!!!!F
#                       `-\    um@T!!!!!!!!!!!!s.      M!!!!!!!!!!F
#                           .#!!!!!!!!!!!!!!!XX!!!!?mM!!!!!!!!!!t~
#                          M!!!@!!!!X!!!!!!!!!!*U!!!!!!!!!!!!!!@
#                         M!!t%!!!W?!!!XX!!!!!!!!!!!!!!!!!!!!X"
#                        :!!t?!!!@!!!!W?!!!!XWWUX!!!!!!!!!!!t
#                        4!!$!!!M!!!!8!!!!!@$$$$$$NX!!!!!!!!-
#                         *P*!!!$!!!!E!!!!9$$$$$$$$%!!!!!!!K
#                            "H*"X!!X&!!!!R**$$$*#!!!!!!!!!>
#                                'TT!?W!!9!!!!!!!!!!!!!!!!M
#                                '!!!!!!!!!!!!!!!!!!!!!!!!F
#                                '!!!!!!!!!!!!!!!!!!!!!!!!>
#                                '!!!!!!!!!!!!!!!!!!!!!!!M
#                                J!!!!!!!!!!!!!!!!!!!!!!!F K!%n.
import actions
import importlib
import logging
import os
import pygerrit
import signal
import yaml
import configuration
from Queue import Queue


class Zoidberg(object):
    def __init__(self, config_file):
        self.config = None
        self.load_config(config_file, raise_exception=True)
        self.startup_tasks = Queue()
        self.running = True

    def run(self):
        try:
            self.process_loop()
        except KeyboardInterrupt:
            pass

        for gerrit_name in self.config.gerrits:
            logging.info('Shutting down stream for %s' % gerrit_name)
            self.config.gerrits[gerrit_name]['client'].stop_event_stream()
            logging.info('Shut down stream for %s' % gerrit_name)

    def process_loop(self):
        # TODO: respond to SIGTERM and clean up nicely
        while self.running:
            # process any startup tasks
            self.process_startup_tasks()
            gerrit_names = self.config.gerrits.keys()
            gerrit_names.sort()
            for gerrit_name in gerrit_names:
                logging.debug('Polling %s for events' % gerrit_name)

                # most things are based around these blocks of configuration
                # which get augmented with useful objects like gerrit clients
                # and regular expressions
                gerrit_cfg = self.config.gerrits[gerrit_name]

                # any failed actions due to connection issues get requeued
                self.enqueue_failed_events(gerrit_cfg)

                event = self.get_event(gerrit_cfg, timeout=0.5)

                while event:
                    self.process_event(event, gerrit_cfg)
                    event = self.get_event(gerrit_cfg, timeout=0.5)

            if self.config_file_has_changed():
                logging.info(
                    'Reloading configuration from %s' % self.config_filename)
                self.load_config(self.config_filename)

    def process_startup_tasks(self):
        # keep track of the tasks that could not be run
        # so we can re-queue them later on
        could_not_run = []

        while not self.startup_tasks.empty():
            task = self.startup_tasks.get(block=False)
            logging.info(
                'Running startup task %s for %s'
                % (task['task']['action'], task['source']['name']))

            # task['task']['action'] will be the name the action is
            # registered with, e.g. zoidberg.FooSomeBars
            a = actions.ActionRegistry.get(task['task']['action'])
            has_run = a().startup(
                self.config, task['task'], task['source'])

            # if the task could not be run for some reason (most likely
            # that the target gerrit was down), we want to put it back
            # in the queue
            if not has_run:
                logging.debug(
                    'Failed running startup task %s for %s'
                    % (task['task']['action'], task['source']['name']))
                could_not_run.append(task)

        # these will be run the next time round, so there's a chance for
        # failed gerrit clients to get connected again
        for task in could_not_run:
            self.startup_tasks.put(task)

    def run_action(self, action_cfg, event, gerrit_cfg):
        logging.info(
            'Running %s for %s' % (action_cfg['action'], gerrit_cfg['name']))
        a = actions.ActionRegistry.get(action_cfg['action'])
        a().run(
            event=event, cfg=self.config, action_cfg=action_cfg,
            source=gerrit_cfg)

    def load_config(self, config_file, raise_exception=False):
        try:
            config_from_yaml = yaml.load(open(config_file, 'r'))
            config = configuration.Configuration(config_from_yaml)
            for module_name in config.plugins:
                action_module = '%s.actions' % module_name
                importlib.import_module(action_module)
            self.validate_config(config)
            self.config_filename = config_file
            self.config_mtime = os.stat(config_file).st_mtime

            # move clients from old config if they have the same connection
            if self.config is not None:
                for gerrit_name in config.gerrits:
                    client = config.gerrits[gerrit_name]['client']
                    old_client = self.config.gerrits[gerrit_name]['client']

                    if old_client == client:
                        logging.debug('Reusing client for %s' % gerrit_name)
                        config.gerrits[gerrit_name]['client'] = old_client
                        self.config.gerrits[gerrit_name]['client'] = None

                self.config.close_clients()
            self.config = config
        except Exception as e:
            logging.error(
                'Could not load configuration file, '
                'encountered errors : ' + e.message)
            if raise_exception:
                raise e

    def validate_config(self, config):
        # TODO: verify startup tasks here too
        for gerrit_name in config.gerrits:
            gerrit_config = config.gerrits.get(gerrit_name)
            for event_type in gerrit_config['events']:
                for action in gerrit_config['events'][event_type]:
                    a = actions.ActionRegistry.get(action['action'])
                    a().validate_config(config, action)

    def connect_client(self, gerrit_config):
            # client connection details
            username = gerrit_config.get('username')
            host = gerrit_config.get('host')
            key_filename = gerrit_config.get('key_filename')
            name = gerrit_config.get('name')
            port = gerrit_config.get('port', 29418)
            client = gerrit_config.get('client')

            try:
                # activate the client's ssh and start streaming events
                if not client.is_active():
                    client.activate_ssh(host, username, key_filename, port)
                    client.start_event_stream()
                    # queue any tasks that need to be run on connection
                    self.queue_startup_tasks(gerrit_config)
            except pygerrit.error.GerritError:
                # if there's an error, log it and we'll try later
                # we can do this because get_client tries to connect
                # if you get a client that is not connected
                logging.error(
                    'Could not connect to %s at %s'
                    % (name, host))

    def queue_startup_tasks(self, gerrit_config):
        if 'startup' in gerrit_config and gerrit_config['startup']:
            for task in gerrit_config['startup']:
                logging.debug(
                    'Queuing startup task %s for %s'
                    % (task['action'], gerrit_config['name']))
                # store the task config block and the gerrit config
                # so the task has access to everything when it's run
                self.startup_tasks.put(
                    {'task': task, 'source': gerrit_config})

    def process_event(self, event, gerrit_cfg):
        project = None

        # deal with the different event structures
        if hasattr(event, 'change'):
            project = event.change.project
        elif hasattr(event, 'ref_update'):
            project = event.ref_update.project

        if project is None:
            # no project? not much we can do!
            return

        # only run for projects we're interested in
        if gerrit_cfg['project_re'].match(project):
            if event.name in gerrit_cfg['events']:
                for action_cfg in gerrit_cfg['events'][event.name]:
                    self.run_action(action_cfg, event, gerrit_cfg)

    def config_file_has_changed(self):
        return self.config_mtime < os.stat(self.config_filename).st_mtime

    def get_client(self, gerrit_cfg):
        client = gerrit_cfg.get('client')
        if not client.is_active():
            # this allows us to lazily connect clients, and reconnect if
            # a gerrit goes down for whatever reason
            logging.info(
                'Client for %s was not active, trying to connect...'
                % gerrit_cfg['name'])
            self.connect_client(gerrit_cfg)
        return client

    def enqueue_failed_events(self, gerrit_cfg):
        client = self.get_client(gerrit_cfg)
        client.enqueue_failed_events()

    def get_event(self, gerrit_cfg, timeout=1):
        client = self.get_client(gerrit_cfg)
        return client.get_event(timeout=timeout)

    def handle_signal(self, signum, frame):
        if signum == signal.SIGTERM:
            self.running = False
