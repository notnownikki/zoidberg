import argparse
import logging
import signal
import zoidberg


def main():
    """Entry point for zoidbergd."""
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', dest='config_file',
                        default='./etc/zoidberg.yaml',
                        help='config yaml path')
    parser.add_argument('-v', '--verbose', dest='verbose',
                        action='store_true')
    options = parser.parse_args()

    log_level = logging.INFO

    if options.verbose:
        log_level = logging.DEBUG

    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(message)s', level=log_level)

    zoidbergd = zoidberg.Zoidberg(options.config_file)
    signal.signal(signal.SIGTERM, zoidbergd.handle_signal)
    zoidbergd.run()
