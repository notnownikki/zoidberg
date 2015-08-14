import json
from collections import namedtuple


def parse(data):
    """Quick, easy, and quite dirty, JSON to object."""
    return json.loads(
        data, object_hook=lambda d: namedtuple(
            'ParsedJsonObject', d.keys())(*d.values()))
