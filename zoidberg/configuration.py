import logging
import re


class Configuration(object):
    """
    Massages the yaml config into something more easily usable.

    Config ends up looking like this:

    {
        'zoidberg-gerrit': {
            'username': '',
            'project-pattern': '',
            'host': '',
            'key_filename': '',
            'events': {
                'comment-added': [
                    {'action': 'ActionClass', 'target': 'other-gerrit'},
                    {'action': 'ActionClass2', 'target': 'other-gerrit'},
                ]
            }
        }
    }

    """
    def __init__(self, cfg):
        self.gerrits = {}
        for gerrit in cfg[0]['gerrits']:
            name = gerrit.keys()[0]
            self.gerrits[name] = {
                'name': name,
                'port': gerrit[name].get('port', 29418)
            }
            for k in ['username', 'project-pattern', 'host', 'key_filename']:
                self.gerrits[name][k] = gerrit[name][k]
            self.gerrits[name]['project_re'] = re.compile(
                gerrit[name]['project-pattern'])
            self.gerrits[name]['events'] = {}
            for event in gerrit[name]['events']:
                event_type = event['type']
                if event_type not in self.gerrits[name]['events']:
                    self.gerrits[name]['events'][event_type] = []
                if 'branch-pattern' in event:
                    event['branch_re'] = re.compile(event['branch-pattern'])
                self.gerrits[name]['events'][event_type].append(event.copy())

    def close_clients(self):
        for gerrit_name in self.gerrits:
            logging.info('Shutting down client for %s' % gerrit_name)
            # shutting down the event stream also closes the client
            self.gerrits[gerrit_name]['client'].stop_event_stream()
            logging.info('Shut down client for %s' % gerrit_name)
