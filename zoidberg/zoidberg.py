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
import argparse
import logging
import pygerrit
import sys
import yaml
import gerrit
import configuration

parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', dest='config_file',
                    default='./etc/zoidberg.yaml',
                    help='config yaml path')
options = parser.parse_args()

logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

# load config
config_from_yaml = yaml.load(open(options.config_file, 'r'))

config = configuration.Configuration(config_from_yaml)


# set up gerrit connections
for gerrit_name in config.gerrits:
    gerrit_config = config.gerrits.get(gerrit_name)
    # client connection details
    username = gerrit_config.get('username')
    host = gerrit_config.get('host')
    key_filename = gerrit_config.get('key_filename')
    name = gerrit_config.get('name')
    # verify actions are valid
    for event_type in gerrit_config['events']:
        for action in gerrit_config['events'][event_type]:
            a = actions.ActionRegistry.get(action['action'])
            a().validate_config(config, action)
    # connect client and store the connected client
    client = gerrit.GerritClient(
        username=username, host=host, key_filename=key_filename)
    logging.info(
        'Connected to %s at %s, gerrit version %s' %
        (name, host, client.gerrit_version()))
    client.start_event_stream()
    gerrit_config['client'] = client

try:
    # event processing loop
    while True:
        for gerrit_name in config.gerrits:
            gerrit_config = config.gerrits[gerrit_name]
            client = config.gerrits[gerrit_name]['client']
            event = client.get_event(timeout=1)
            while event:
                project = None
                if hasattr(event, 'change'):
                    project = event.change.project
                elif hasattr(event, 'ref_update'):
                    project = event.ref_update.project
                if gerrit_config['project_re'].match(project):
                    if event.name in gerrit_config['events']:
                        for action in gerrit_config['events'][event.name]:
                            logging.info('Running %s for %s' % (
                                action['action'], gerrit_name))
                            a = actions.ActionRegistry.get(action['action'])
                            a().run(
                                event=event, cfg=config, action_cfg=action,
                                source=gerrit_config)
                event = client.get_event(timeout=1)
except KeyboardInterrupt:
    for gerrit_name in config.gerrits:
        logging.info('Shutting down stream for %s' % gerrit_name)
        # config.gerrits[gerrit_name]['client'].stop_event_stream()
        logging.info('Shut down stream for %s' % gerrit_name)
