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
import logging
import os
import pygerrit
import time
import yaml
import configuration


class Zoidberg(object):
    def __init__(self, config_file):
        self.load_config(config_file)

    def validate_actions(self, config):
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
            except pygerrit.error.GerritError:
                # if there's an error, log it and we'll try later
                logging.error(
                    'Could not connect to %s at %s'
                    % (name, host))

    def load_config(self, config_file):
        config_from_yaml = yaml.load(open(config_file, 'r'))
        config = configuration.Configuration(config_from_yaml)
        self.validate_actions(config)
        self.config_filename = config_file
        self.config_mtime = os.stat(config_file).st_mtime
        self.config = config
        # TODO: if any events have come in, transfer them across
        # to the new clients

    def run_action(self, action_cfg, event, gerrit_cfg):
        logging.info(
            'Running %s for %s' % (action_cfg['action'], gerrit_cfg['name']))
        a = actions.ActionRegistry.get(action_cfg['action'])
        a().run(
            event=event, cfg=self.config, action_cfg=action_cfg,
            source=gerrit_cfg)

    def process_event(self, event, gerrit_cfg):
        project = None

        if hasattr(event, 'change'):
            project = event.change.project
        elif hasattr(event, 'ref_update'):
            project = event.ref_update.project

        if project is None:
            # no project? not much we can do!
            return

        if gerrit_cfg['project_re'].match(project):
            if event.name in gerrit_cfg['events']:
                for action_cfg in gerrit_cfg['events'][event.name]:
                    self.run_action(action_cfg, event, gerrit_cfg)

    def config_file_has_changed(self):
        return self.config_mtime < os.stat(self.config_filename).st_mtime

    def get_client(self, gerrit_cfg):
        client = gerrit_cfg['client']
        if not client.is_active():
            logging.info(
                'Client for %s was not active, trying to connect...'
                % gerrit_cfg['name'])
            time.sleep(1)
            self.connect_client(gerrit_cfg)
        return client

    def enqueue_failed_events(self, gerrit_cfg):
        client = self.get_client(gerrit_cfg)
        client.enqueue_failed_events()

    def get_event(self, gerrit_cfg, timeout=1):
        client = self.get_client(gerrit_cfg)
        return client.get_event(timeout=timeout)

    def process_loop(self):
        while True:
            for gerrit_name in self.config.gerrits:
                logging.debug('Polling %s for events' % gerrit_name)
                gerrit_cfg = self.config.gerrits[gerrit_name]

                # any failed actions due to connection issues get requeued
                self.enqueue_failed_events(gerrit_cfg)

                event = self.get_event(gerrit_cfg, timeout=1)
                while event:
                    self.process_event(event, gerrit_cfg)
                    event = self.get_event(gerrit_cfg, timeout=1)
            if self.config_file_has_changed():
                self.config.close_clients()
                self.load_config(self.config_filename)

    def run(self):
        try:
            self.process_loop()
        except KeyboardInterrupt:
            for gerrit_name in self.config.gerrits:
                logging.info('Shutting down stream for %s' % gerrit_name)
                self.config.gerrits[gerrit_name]['client'].stop_event_stream()
                logging.info('Shut down stream for %s' % gerrit_name)
