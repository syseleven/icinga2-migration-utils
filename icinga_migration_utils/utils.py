import collections
import datetime
import logging
import textwrap

from boltons.iterutils import remap
from nested_dict import nested_dict

from ruamel import yaml


logger = logging.getLogger(__name__)

CHECK_COMMAND_MAP = {
    'check_ping_.*': 'ping',
}


def format_date(datetime_obj):
    """
    Format date for germans

    :param datetime_obj: 
    :return: 
    """
    return datetime_obj.strftime('%Y-%m-%d %H:%M:%S')


def ndict(data):
    """
    Create a defaultdict-like dictionary that allows accessing nested keys without getting
    KeyErrors or TypeErrors.

    Regular dict:
    {'a': 'a', 'b': None}['c'] => KeyError
    {'a': 'a', 'b': None}['b']['c'] => TypeError

    ndict:
    {'a': 'a', 'b': None}['c'] => {}
    {'a': 'a', 'b': None}['b']['c'] => {}

    :param data: dictionary data to convert
    :type data: dict
    :return:
    """
    data = remap(data, lambda p, k, v: v is not None)
    return nested_dict(data)


def pretty_print_dict(d, indent=''):
    """
    Pretty print dictionary

    :param d: dictionary
    :type d: dict
    :param indent: indentation
    :type indent: str
    :return:
    """
    d = collections.OrderedDict(sorted(d.items()))
    d = dict(d)
    pretty_service = yaml.dump(d, None, default_flow_style=False)
    return textwrap.indent(pretty_service, indent)


def unixtimestamp_tostr(timestamp):
    """
    Convert unix timestamp to string

    :param timestamp: Unix timestamp
    :type timestamp: int
    :return: Formatted date
    :rtype: str
    """
    return datetime.datetime.utcfromtimestamp(int(timestamp)).strftime('%Y-%m-%d %H:%M:%S')
