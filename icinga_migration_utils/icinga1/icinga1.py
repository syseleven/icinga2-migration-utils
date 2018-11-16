#!/usr/bin/env python
#
# Utilities to parse Icinga 1 cache files into dictionaries
#
import glob
import logging
import os
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

OBJECT_CACHE_REGEX = r'define\s+(?P<object_type>\w+)\s+\{\n' \
                     r'|\t(?P<keyonly>\w+)\t\n|\t(?P<key>\w+)\s+(?P<value>[^\n]*)\n|\t' \
                     r'\}'
STATUS_FILE_REGEX = r'(?P<object_type>\w+)\s+\{\n|\t(?P<key>\w+)\=(?P<value>[^\n]*)\n|\t\}'

CACHE_DIR = os.path.expanduser('~/.cache/icingadiff')

DEFAULT_OBJECTS_FILES = os.path.join(CACHE_DIR, 'objects_monitoring*.cache')
DEFAULT_STATUS_FILES = os.path.join(CACHE_DIR, 'status_monitoring*.cache')


class Icinga1Error(Exception):
    pass


class StatusType(object):
    """
    Icinga 1 status types
    """
    CONTACTSTATUS = 'contactstatus'
    SERVICECOMMENT = 'servicecomment'
    SERVICESTATUS = 'servicestatus'
    HOSTSTATUS = 'hoststatus'
    SERVICEDOWNTIME = 'servicedowntime'
    HOSTCOMMENT = 'hostcomment'
    PROGRAMSTATUS = 'programstatus'
    HOSTDOWNTIME = 'hostdowntime'
    INFO = 'info'


class ObjectType(object):
    """
    Icinga 1 Object types
    """
    COMMAND = 'command'
    CONTACT = 'contact'
    CONTACTGROUP = 'contactgroup'
    HOST = 'host'
    HOSTGROUP = 'hostgroup'
    MODULE = 'module'
    SERVICE = 'service'
    SERVICEDEPENDENCY = 'servicedependency'
    SERVICEGROUP = 'servicegroup'
    TIMEPERIOD = 'timeperiod'


def parse_icinga_cache(file, source, regex):
    """
    Parse and store Icinga1 config from downloaded object cache file.

    Will exclude all hosts where hostname or address matches
    any pattern in icinga1_host_exclude_patterns.txt

    :param file: Cache file to parse
    :param source: Related monitoring server (monitoring0X)
    :param regex: 
    :return: 
    """
    logger.debug("Parsing cache file {}".format(file))
    content = open(file).read()
    matches = re.finditer(regex, content, re.DOTALL)

    result = []
    obj = {}

    # Iterate through all objects in cache file
    for match in matches:
        groups = match.groups()

        # All values None -> End of match
        if all(not x for x in groups):
            result.append(obj)
            obj = {}
        else:
            groupdict = match.groupdict()
            # save object type for next iteration
            if groupdict['object_type']:
                obj['object_type'] = groupdict['object_type']
                obj['monitoring_source'] = source

            # key with empty value
            elif groupdict.get('keyonly', None):
                key = groupdict['keyonly']
                obj[key] = None

            # key-value
            elif groupdict['key'] and groupdict['value']:
                key = groupdict['key']
                value = groupdict['value']
                obj[key] = value
    return result


class Icinga1Config(object):
    """
    Provide access to Icinga1/Nagios config
    """

    def __init__(self, status_files=None, objects_files=None):
        """
        :param status_files: Icinga/Nagios status files to parse (supports globbing)
        :param objects_files: Icinga objects files to parse (supports globbing)
        """
        self.status_files = status_files or os.environ.get('ICINGA_STATUS_FILES',
                                                           DEFAULT_STATUS_FILES)
        self.objects_files = objects_files or os.environ.get('ICINGA_OBJECT_FILES',
                                                             DEFAULT_OBJECTS_FILES)
        self._status = []
        self._objects = []
        self._hostdowntimes = []
        self._servicedowntimes = []
        self._service_acknowledgements = []
        self._host_acknowledgements = []
        self._contacts = []

    @property
    def objects(self):
        """
        Parse objects file on first access to objects.

        Object types: 
            'command', 'contact', 'contactgroup', 'host', 'hostgroup', 'module', 'service', 
            'servicedependency', 'servicegroup', 'timeperiod'
        :return: 
        """
        if not self._objects:
            for objects_file in glob.glob(self.objects_files):
                source = re.findall(r'(monitoring[\d]+)\.cache', objects_file)[0]
                self._objects.extend(
                    parse_icinga_cache(objects_file, source, OBJECT_CACHE_REGEX))
        if not self._objects:
            raise Exception("Error - no objects found in object cache files ({})"
                            .format(self.objects_files))
        return self._objects

    @property
    def status(self):
        """
        Parse status file on first access to status.

        Status object types: 
            'contactstatus', 'hostcomment', 'hostdowntime', 'hoststatus', 'info', 
            'programstatus', 'servicecomment', 'servicedowntime', 'servicestatus'
        :return: 
        """
        if not self._status:
            for status_file in glob.glob(self.status_files):
                source = re.findall(r'(monitoring[\d]+)\.cache', status_file)[0]
                self._status.extend(
                    parse_icinga_cache(status_file, source, STATUS_FILE_REGEX))
        if not self._status:
            raise Exception("Error - no objects found in status cache files"
                            .format(self.status_files))
        return self._status

    def _get_objects(self, object_type, **kwargs):
        objects = [obj for obj in self.objects if obj.get('object_type', None) == object_type]
        if kwargs:
            # Filter dictionary by key-value pairs in kwargs
            for key, value in kwargs.items():
                objects = [obj for obj in objects
                           if key in obj.keys() and obj[key] == value]
        return objects

    def _get_status(self, object_type, **kwargs):
        objects = [obj for obj in self.status if obj.get('object_type', None) == object_type]
        if kwargs:
            # Filter dictionary by key-value pairs in kwargs
            objects = [obj for key, value in kwargs.items()
                       for obj in objects
                       if key in obj.keys() and obj[key] == value]
        return objects

    def get_hosts(self, **kwargs):
        """
        Get hosts, optionally filtered by any attribute.
        
        Common host attributes:
            active_checks_enabled
            address
            check_command
            check_freshness
            check_interval
            event_handler_enabled
            failure_prediction_enabled
            first_notification_delay
            flap_detection_enabled
            flap_detection_options
            freshness_threshold
            high_flap_threshold
            host_name
            initial_state
            low_flap_threshold
            max_check_attempts
            notification_interval
            notification_options
            notifications_enabled
            object_type
            obsess_over_host
            passive_checks_enabled
            process_perf_data
            retain_nonstatus_information
            retain_status_information
            retry_interval
            stalking_options
        Host attributes not available for all hosts:
            alias
            check_period
            contact_groups
            contacts
            notes
            notification_period        
        
        :param kwargs: filter for hosts by attribute, e.g. address='123.123.123.123'
        :return: 
        """
        return self._get_objects(ObjectType.HOST, **kwargs)

    def get_hosts_dict(self, **kwargs):
        """
        Get hosts as dictionary by hostname for faster lookups

        :param kwargs:
        :return:
        """
        host_dict = {}
        for host in self.get_hosts(**kwargs):
            host_dict[host['host_name']] = host
        return host_dict

    def get_hoststatus_by_host(self):
        """
        Get host status by host for faster lookups

        :return: ['hostname':HOSTSTATUS]
        """
        host_status_dict = {}
        host_status = [
            status for status in self.status
            if status['object_type'] == StatusType.HOSTSTATUS
        ]
        for status in host_status:
            host_status_dict[status['host_name']] = status
        return host_status_dict

    def get_servicestatus(self, hostname):
        """
        Get service status for specific host
        :param hostname:
        :return:
        """
        return [
            status for status in self.status
            if status['object_type'] == StatusType.SERVICESTATUS
            and status['host_name'] == hostname
        ]

    def get_servicestatus_by_host(self):
        """
        Get service status by host for faster lookups

        :return: ['hostname':[SERVICESTATUS1, SERVICESTATUS2, ...]]
        """
        service_status_dict = defaultdict(list)
        service_status = [
            status for status in self.status
            if status['object_type'] == StatusType.SERVICESTATUS
        ]
        for status in service_status:
            service_status_dict[status['host_name']].append(status)
        return service_status_dict

    def get_services(self, hostname=None, **kwargs):
        """
        Get services, optionally filtered by any attribute.
        
        Common service attributes: 
            active_checks_enabled
            check_command
            check_freshness
            check_interval
            check_period
            event_handler_enabled
            failure_prediction_enabled
            first_notification_delay
            flap_detection_enabled
            flap_detection_options
            freshness_threshold
            high_flap_threshold
            host_name
            initial_state
            is_volatile
            low_flap_threshold
            max_check_attempts
            notification_interval
            notification_options
            notification_period
            notifications_enabled
            object_type
            obsess_over_service
            parallelize_check
            passive_checks_enabled
            process_perf_data
            retain_nonstatus_information
            retain_status_information
            retry_interval
            service_description
            stalking_options
        Attributes not available for all services:
            contact_groups
            contacts
            event_handler
            notes
            notes_url 
                       
        :param hostname: hostname
        :param kwargs: filter for services by key-value
        :rtype: list
        :return: list of services
        """
        if hostname:
            kwargs['host_name'] = hostname
        return self._get_objects(ObjectType.SERVICE, **kwargs)

    def get_services_by_hostname(self, **kwargs):
        """
        Get dictionary of all Services, grouped by hostname

        :return:
        :rtype: dict
        """
        services = defaultdict(list)

        for service in self.get_services(**kwargs):
            services[service['host_name']].append(service)
        return services

    def get_downtimes(self, hostname):
        """
        Get all downtimes related to host

        :param hostname:
        :return:
        """
        return [
            downtime for downtime in self.hostdowntimes + self.servicedowntimes
            if downtime['host_name'] == hostname
        ]

    @property
    def hostdowntimes(self):
        """
        Get host downtimes

        :return: 
        """
        if not self._hostdowntimes:
            self._hostdowntimes = self._get_status(StatusType.HOSTDOWNTIME)

        return self._hostdowntimes

    @property
    def servicedowntimes(self):
        """
        Get service downtimes

        :return: 
        """
        if not self._servicedowntimes:
            self._servicedowntimes = self._get_status(StatusType.SERVICEDOWNTIME)

        return self._servicedowntimes

    def get_acknowledgements(self, hostname):
        """
        Get all acks related to host

        :param hostname: hostname
        :return:
        """
        return [ack for ack in self.service_acknowledgements + self.host_acknowledgements
                if ack['host_name'] == hostname]

    @property
    def service_acknowledgements(self):
        """
        Get service acknowledgements

        :return:
        :rtype: list
        """
        if not self._service_acknowledgements:
            # entry type 4 => User comment
            # (see https://www.icinga.com/docs/icinga2/latest/doc/09-object-types/#comment)
            self._service_acknowledgements = \
                [status for status in self._get_status(StatusType.SERVICECOMMENT)
                 if status['entry_type'] == '4']
        return self._service_acknowledgements

    @property
    def host_acknowledgements(self):
        """
        Get host acknowledgements

        :return:
        :rtype: list
        """
        if not self._host_acknowledgements:
            # entry type 4 => User comment
            # (see https://www.icinga.com/docs/icinga2/latest/doc/09-object-types/#comment)
            self._host_acknowledgements = \
                [status for status in self._get_status(StatusType.HOSTCOMMENT)
                 if status['entry_type'] == '4']
        return self._host_acknowledgements

    @property
    def contacts(self):
        if not self._contacts:
            self._contacts = self._get_objects(ObjectType.CONTACT)

            # Deduplicate contacts - same on each monitoring host (after nightly sync)
            for c in self._contacts:
                c.pop('monitoring_source')
            # need to convert dicts into hashable tuples to deduplicate
            self._contacts = [dict(t) for t in set([tuple(d.items()) for d in self._contacts])]
        return self._contacts
