import configparser
import logging
import os
import sys
from collections import defaultdict

import progressbar
from icinga2api.client import Client
from icinga_migration_utils.icinga2 import HostNotFoundException
from icinga_migration_utils.utils import ndict
from requests.exceptions import ChunkedEncodingError

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_FILE = '~/.icingadiffrc'


class Icinga2Error(Exception):
    pass


class Icinga2Config(object):
    """
    Convenience wrapper for Icinga2 client.

    OS environment parameters:
       ICINGADIFF_CONFIG: alternative configuration file (defaults to ~/.icingadiffrc)
    """
    def __init__(self, config=None):
        if not config:
            config_environ = os.environ.get('ICINGADIFF_CONFIG')

            if config_environ:
                cfg_file = config_environ
            else:
                cfg_file = os.path.expanduser(DEFAULT_CONFIG_FILE)

            if not os.path.isfile(cfg_file):
                sys.exit("Please configure icingadiff first (see README.md)".format(cfg_file))
            config = configparser.RawConfigParser()
            config.read(cfg_file)
        url = config['icinga2_web']['url']
        username = config['icinga2_web']['username']
        password = config['icinga2_web']['password']
        self.retries = int(config['icinga2_web'].get('retries', 5))

        if type(config) == configparser.RawConfigParser:
            timeout = config['icinga2_web'].getint('timeout', 30)
            ignore_insecure_requests = config.getboolean('icinga2_web', 'ignore_insecure_requests')
        else:
            timeout = config['icinga2_web'].get('timeout', 30)
            ignore_insecure_requests = config['icinga2_web']\
                .get('ignore_insecure_requests', True)

        self.config = config
        self.client = Client(url, username=username, password=password,
                             ignore_insecure_requests=ignore_insecure_requests, timeout=timeout)

    def get_objects_list(self, *args, **kwargs):
        for i in range(0, self.retries+1):
            try:
                return self.client.objects.list(*args, **kwargs)
            except ChunkedEncodingError:
                logger.error("Error getting objects (retry: {}/{})".format(i, self.retries))
        raise Icinga2Error("Failed getting objects with {} retries".format(self.retries))

    def get_services(self, host_address=None, attrs=None, joins=None, host_name=None,
                     service_name=None):
        """
        Retrieve Icinga2 services from API.
        Attributes need to be reduced if trying to get all services.
        
        :param host_address: if set, query for services for given IP address
        :param host_name: if set, query for services for given hostname
        :param attrs: Attributes to fetch from API
        :param joins: Joins to perform
        :param service_name: Service name
        :return:
        """
        filters = []
        filter_vars = {}

        # Reduce attributes by default if querying for *all* services, otherwise it might fail
        if attrs is None and not host_name:
            attrs = ['check_command', 'name', 'vars', 'enable_notifications',
                     'last_check_result', 'notes_url', 'display_name']

        if not joins:
            joins = ['host.address', 'host.name']

        if host_address:
            filters.append('host.address==host_address')
            filter_vars['host_address'] = host_address

        if host_name:
            filters.append('host.name==host_name')
            filter_vars['host_name'] = host_name

        if service_name:
            filters.append('service.name==service_name')
            filter_vars['service_name'] = service_name

        filters = ' && '.join(filters)
        services = self.get_objects_list(
            object_type='Service', joins=joins, filter=filters, attrs=attrs,
            filter_vars=filter_vars)
        return services

    def get_services_by_hostname(self, **kwargs):
        """
        Get services as dictionary by hostname

        :return: 
        """
        services_dict = defaultdict(list)
        for service in self.get_services(**kwargs):
            services_dict[service['joins']['host']['name']].append(service)
        return services_dict

    def get_host(self, host_name):
        hosts = self.get_hosts(host_name=host_name)
        if not hosts:
            raise HostNotFoundException("Host '{}' not found".format(host_name))
        return hosts[0]

    def get_hosts(self, attrs=None, host_name=None, joins=None):
        """
        Get hosts

        :param attrs: attributes
        :param host_name: host name
        :param joins: specifify joins (set to True for all joins)
        :return:
        """
        query_dict = {
            'object_type': 'Host',
            'attrs': attrs,
            'joins': joins
        }
        if host_name:
            query_dict.update({
                'filter': 'host.name==hostname',
                'filter_vars': {'hostname': host_name},
            })
        return self.client.objects.list(**query_dict)

    def get_hosts_dict(self, **kwargs):
        """
        Get hosts as dictionary by hostname

        :return:
        """
        hosts_dict = {}
        for host in self.get_hosts(**kwargs):
            hosts_dict[host['attrs']['name']] = host
        return hosts_dict

    def get_downtimes(self, **query):
        """
        Get downtime with query.
        Querydict will be converted:
        {'host_name': 'asdf', 'service_name': 'asdf'}
        => {'host.name': 'asdf', 'service.name': 'asdf'}

        Example:
        get_downtimes(host_name='foo', downtime_comment='bar')
        :param query:
        :return:
        """
        query_filter = None
        filter_vars = None
        if query:
            query_filters = []
            filter_vars = {}
            for key in query:
                query_filters.append('{}=={}'.format(
                    key.replace('host_name', 'host.name').replace('service_name', 'service.name'), key))
                filter_vars[key] = query[key]
            query_filter = ' && '.join(query_filters)
        logger.debug("Filter: {}, filter vars: {}".format(query_filter, filter_vars))
        downtimes = self.client.objects.list(
            object_type='Downtime', joins=['host.address', 'host.name', 'service.name'],
            filter=query_filter, filter_vars=filter_vars
        )
        return downtimes

    def schedule_host_downtime(self, host_name, author, comment, start_time, end_time,
                               duration, fixed):
        response = self.client.actions.schedule_downtime(
            object_type='Host',
            filter='match("{}", host.name)'.format(host_name),
            author=author,
            comment=comment,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            fixed=fixed
        )
        if response['results']:
            try:
                message = response['results'][0]['status']
            except:
                message = ''
            logger.info("Created downtime - response: '{}'".format(message))
            logger.debug("Got response: {0}".format(response))
        else:
            logger.error("Error adding downtime is {} missing in Icinga2?".format(host_name))

    def schedule_service_downtime(self, host_name, service_name, downtime_author,
                                  downtime_comment, downtime_start_time, downtime_end_time,
                                  downtime_duration, downtime_fixed):
        response = self.client.actions.schedule_downtime(
            object_type='Service',
            filter='host.name==hostname && service.name==servicename',
            filter_vars={'hostname': host_name, 'servicename': service_name},
            author=downtime_author,
            comment=downtime_comment,
            start_time=downtime_start_time,
            end_time=downtime_end_time,
            duration=downtime_duration,
            fixed=downtime_fixed
        )
        if response['results']:
            try:
                message = response['results'][0]['status']
            except:
                message = ''
            logger.info("Created downtime - response: '{}'".format(message))
            logger.debug("Got response: {0}".format(response))
        else:
            logger.error("Error adding downtime is {}!{} missing in Icinga2?"
                         .format(host_name, service_name))

    def get_service_problems(self):
        """
        Get service problems

        :return: 
        """
        return self.client.objects.list(
            object_type='Service', joins=['host.address'],
            filter='service.state!=ServiceOK')

    def get_acknowledgements(self, host_name=None, author=None, comment=None,
                             service_name=None):
        """
        Get acknowledgements (=comments)

        :param host_name:
        :param author:
        :param comment:
        :param service_name:
        :return:
        """
        filters = []
        filter_vars = {}
        if host_name:
            filters.append('host.name==hostname')
            filter_vars['hostname'] = host_name
        if author:
            filters.append('comment.author==author')
            filter_vars['author'] = author
        if comment:
            filters.append('comment.text==text')
            filter_vars['text'] = comment
        if service_name:
            filters.append('service.name==servicename')
            filter_vars['servicename'] = service_name
        filters = ' && '.join(filters)
        return self.client.objects.list(
            'Comment',
            joins=['host.name'],
            filter=filters,
            filter_vars=filter_vars
        )

    def acknowledge_service(self, host_name, service_name, author, comment):
        """
        Acknowledge service

        :param host_name: hostname
        :param service_name: service name
        :param author: author
        :param comment: comment
        :return:
        """
        response = self.client.actions.acknowledge_problem(
            'Service',
            filter='host.name=="{0}" && service.name=="{1}"'.format(host_name, service_name),
            author=author,
            comment=comment
        )
        if not response['results'] or response['results'][0]['code'] != 200:
            logger.error("Did not acknowledge service - response: {}".format(response))
            return False
        else:
            logger.info("Acknowledging service: {}!{}"
                        .format(host_name, service_name, service_name))
            return True

    def acknowledge_host(self, host_name, author, comment):
        """
        Acknowledge host

        :param host_name: hostname
        :param author: author
        :param comment: comment
        :return:
        """
        response = self.client.actions.acknowledge_problem(
            'Host',
            filter='host.name=="{0}"'.format(host_name),
            author=author,
            comment=comment
        )
        if not response['results'] or response['results'][0]['code'] != 200:
            logger.error("Did not acknowledge host '{}' - response: {}"
                         .format(host_name, response))
            return False
        else:
            logger.info("Acknowledging host: {}".format(host_name))
            return True

    def get_users(self, username=None, pager=None):
        """
        Get users

        :param username: user name
        :param pager: pager
        :return: 
        """
        filters = []
        filter_vars = {}
        if username:
            filters.append('user.name==username')
            filter_vars['username'] = username
        if pager:
            filters.append('user.pager==pager')
            filter_vars['pager'] = pager
        filters = ' && '.join(filters)

        return self.client.objects.list(
            object_type='User', filter=filters, filter_vars=filter_vars)

    def get_notifications(self, attrs=None, hostname=None, filter_customer_notifications=False):
        """
        Get all notifications

        :param attrs: attributes
        :param hostname: hostname
        :param filter_customer_notifications: Filter for customer notifications
        :return:
        """
        filters = []
        if hostname:
            filters.append('host.name=="{}"'.format(hostname))

        if filter_customer_notifications:
            filters.append('match("customer -> *", notification.name)')

        filter = ' && '.join(filters)

        return self.get_objects_list(
            'Notification',
            attrs=attrs,
            filter=filter
        )

    def get_host_notifications(self, hostname=None, attrs=None,
                               filter_customer_notifications=False):
        """
        Get host notifications (exclude service notifications)

        :param hostname: hostname
        :param attrs: attributes
        :param filter_customer_notifications: Filter for customer notifications
        :return:
        """
        filters = []
        filter_vars = {}

        if hostname:
            filters.append('host.name==hostname')
            filter_vars['hostname'] = hostname

        if filter_customer_notifications:
            filters.append('notification.name=="customer -> Host"')

        # Exclude service notifications
        filters.append('service.name==null')
        filters = ' && '.join(filters)

        return self.client.objects.list(
            'Notification',
            filter=filters,
            filter_vars=filter_vars,
            attrs=attrs
        )

    def get_service_notifications(self, hostname=None, servicename=None, attrs=None,
                                  filter_customer_notifications=False):
        """
        Get service notifications

        :param hostname: hostname
        :param servicename: servicename
        :param attrs: attributes
        :param filter_customer_notifications: Filter for customer notifications
        :return:
        """
        filters = []
        filter_vars = {}

        if hostname:
            filters.append('host.name==hostname')
            filter_vars['hostname'] = hostname

        if filter_customer_notifications:
            filters.append('notification.name=="customer -> Service"')

        if servicename:
            filters.append('service.name==servicename')
            filter_vars['servicename'] = servicename
        else:
            # Exclude host notifications
            filters.append('service.name!=null')

        filters = ' && '.join(filters)

        filters += ' && service.name!=null'

        return self.client.objects.list(
            'Notification',
            filter=filters,
            filter_vars=filter_vars,
            attrs=attrs
        )

    def get_service_notification_contacts(self, hostname=None):
        """
        Extract users and groups from all service notifications

        :param hostname: hostname
        :return:
        """
        result = defaultdict(dict)
        icinga2_users = self.get_users()
        notifications = self.get_notifications(
            attrs=['users', 'user_groups', 'host_name', 'service_name'],
            hostname=hostname,
            filter_customer_notifications=True
        )

        # Very long running operation when applied for all hosts - show progressbar
        notification_iterator = notifications
        if not hostname:
            bar = progressbar.ProgressBar()
            notification_iterator = bar(notifications)

        # Iterate through all notifications
        for notification in notification_iterator:
            key = "{}".format(notification['attrs']['host_name'])
            usernames = []
            users = []
            groups = []

            notification_groups = notification['attrs']['user_groups']
            if notification_groups:
                groups.extend(notification_groups)

            notification_users = notification['attrs']['users']
            if notification_users:
                usernames.extend(notification_users)

            # merge host and service notifications
            if notification['attrs']['service_name']:
                key += "!{}".format(notification['attrs']['service_name'])

            for username in usernames:
                users.extend([
                    {'name': user['attrs']['name'],
                     'email': user['attrs']['email'],
                     'groups': user['attrs']['groups']}
                    for user in icinga2_users
                    if user['attrs']['name'] == username])

            for group in groups:
                users.extend([
                    {'name': user['attrs']['name'],
                     'email': user['attrs']['email'],
                     'groups': user['attrs']['groups']}
                    for user in icinga2_users
                    if group in user['attrs']['groups']])

            result[key] = {'users': users, 'groups': groups}

        # Iterate through all services with custom notifications
        services_with_overrides = [
            service for service in self.get_services(
                attrs=['vars', 'check_command', 'name', 'host_name'])
            if ndict(service)['attrs']['vars']['notifications']['users']
        ]
        if hostname:
            services_with_overrides = [
                service for service in services_with_overrides
                if service['attrs']['host_name'] == hostname
            ]
        for service in services_with_overrides:
            if service['name'] not in result.keys():
                result[service['name']] = {'users': [], 'groups': []}

            for username in service['attrs']['vars']['notifications']['users']:
                user = [{
                    'name': x['attrs']['name'],
                    'email': x['attrs']['email'],
                    'groups': x['attrs']['groups']}
                    for x in icinga2_users if x['name'] == username][0]
                result[service['name']]['users'].append(user)

        return dict(result)
    
    def set_active_checks(self, hostname, enabled, comment=None, author=None):
        """
        Toggle active checks for host and all related services.
        If enabled, will add host comment "comment" .
        If disabled, will remove host comment "comment".

        :param hostname: hostname
        :param enabled: Enable or disable
        :type enabled: bool
        :param comment: comment
        :param author: author
        :return:
        """
        if not comment:
            comment = '{} active checks'.format('Enabling' if enabled else 'Disabling')

        if not author:
            author = os.environ['USER']

        logger.info("{} active checks for host '{}' with comment '{}'"
                    .format('Enabling' if enabled else 'Disabling', hostname, comment))
        result = self.client.objects.update(
            object_type='Host',
            name=hostname,
            attrs={'attrs': {'enable_active_checks': enabled}}
        )
        logger.debug("Set active host checks result: {}".format(result))

        # Remove comment when active checks are enabled again, otherwise add comment
        if enabled:
            result = self.client.actions.remove_comment(
                object_type='Host',
                filter='host.name==hostname && comment==comment',
                filter_vars={'hostname': hostname, 'comment': comment},
            )
            logger.debug("Remove comment result: {}".format(result))
        else:
            result = self.client.actions.add_comment(
                object_type='Host',
                filter='host.name==hostname',
                filter_vars={'hostname': hostname},
                author=author,
                comment=comment)
            logger.debug("Add comment result: {}".format(result))

        # Set active checks for all related services
        services = self.client.objects.list(
            object_type='Service',
            filter='host.name==hostname',
            filter_vars={'hostname': hostname},
            attrs=['name']
        )
        service_names = [service['name'] for service in services]
        for servicename in service_names:
            logger.info("{} active checks for service '{}'"
                        .format('Enabling' if enabled else 'Disabling', servicename))
            result = self.client.objects.update(
                object_type='Service',
                name=servicename,
                attrs={'attrs': {'enable_active_checks': enabled}}
            )
            logger.debug("Set active service checks result: {}".format(result))

    def set_host_notifications(self, hostname, enabled, notes):
        """
        Set enable_notifications for host
        :param hostname: hostname 
        :param enabled: enabled
        :param notes: notes
        :return: 
        """
        return self.client.objects.update(
            'Host', hostname, {'attrs': {'enable_notifications': enabled, 'notes': notes}}
        )

    def set_service_notifications(self, hostname, servicename, enabled, notes):
        """
        Set enable_notifications for host
        :param hostname: hostname
        :param servicename: servicename
        :param enabled: enabled
        :param notes: notes
        :return: 
        """
        obj = '{}!{}'.format(hostname, servicename)
        return self.client.objects.update(
            'Service', obj, {'attrs': {'enable_notifications': enabled, 'notes': notes}}
        )
