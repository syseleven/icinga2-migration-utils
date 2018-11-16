"""
Utilities to compare Icinga1 and Icinga2 config.
Serves more for demonstration purposes - most of this is highly related to the
configuration as used by SysEleven.
"""
import csv
import json
import logging
import re
import sys
import textwrap
from collections import defaultdict, Counter
from datetime import datetime

import progressbar

from icinga_migration_utils.icinga1.icinga1 import Icinga1Config
from icinga_migration_utils.icinga2.icinga2 import Icinga2Config
from icinga_migration_utils.migrate import MIGRATION_COMMENT_SUFFIX
from icinga_migration_utils.utils import format_date, ndict

from ruamel import yaml


logger = logging.getLogger(__name__)


def compare_hosts(icinga1=Icinga1Config(), icinga2=Icinga2Config()):
    """
    Compare hosts:
    * check if hosts exist in Icinga2
    * compare if SLA is set in Icinga2 if set in Icinga1
    * Compare check_interval
    * Compare max_check_attempts
    * Compare retry_interval

    :param icinga1: Icinga1Config
    :param icinga2: Icinga2Config
    :return:
    """
    icinga1_hosts = icinga1.get_hosts_dict()
    icinga2_hosts = icinga2.get_hosts_dict()

    result = defaultdict(list)

    compare_attributes = ['check_interval', 'max_check_attempts', 'retry_interval']

    for hostname in sorted(icinga1_hosts):
        if hostname not in icinga2_hosts:
            result['missing'].append(hostname)
            print("{}: {}".format('Missing in Icinga2', hostname))
        else:
            icinga1_host = icinga1_hosts[hostname]
            icinga2_host = icinga2_hosts[hostname]

            if icinga1_host.get('notes') == 'no-sla' \
                    and not ndict(icinga2_host)['attrs']['vars']['nosla']:
                result['nosla'].append(hostname)
                print("{}: {} (Icinga1: {}, Icinga2: {})".format(
                    "Different SLA: ", hostname,
                    icinga1_host.get('notes') == 'no-sla',
                    'nosla' in icinga2_host['attrs']['vars']))

            for attrib in compare_attributes:
                icinga1_attrib = float(icinga1_host[attrib])
                icinga2_attrib = float(icinga2_host['attrs'][attrib])

                if attrib in ['retry_interval', 'check_interval']:
                    icinga1_attrib *= 60

                if icinga1_attrib != icinga2_attrib:
                    result[attrib].append((hostname, icinga1_host[attrib],
                                           icinga2_host['attrs'][attrib]))
                    print("{}: {} (Icinga1: {}, Icinga2: {})".format(
                        "Different {} ".format(attrib), hostname, icinga1_host[attrib],
                        icinga2_host['attrs'][attrib]))
    return result


def compare_services(output=None, hostname=None, icinga1=Icinga1Config(),
                     icinga2=Icinga2Config()):
    """
    Compare Services retrieved from Icinga1 (cache file) and Icinga2 (REST API) per host.

    Compares:
    * Service exists in Icinga2
    * notification state is the same (enable_notifications)
    * no-sla attribute is the same
    * notes-url is the same

    Example output:
        10.3.147.6
        Icinga1 services missing in Icinga2:
        check_http
        SSH
        Icinga2 services missing in Icinga1:
        check_ssh

        10.3.147.15
        Icinga1 services missing in Icinga2:
        SSH
        Icinga2 services missing in Icinga1:
        check_ssh

    :param output: output filename (write to stdout if None)
    :type output: str
    :param hostname: Hostname
    :param icinga1: Icinga1Config
    :param icinga2: Icinga2Config
    :return:
    """
    logger.info("Retrieving Icinga1 services")
    icinga1_services_all = icinga1.get_services_by_hostname()
    icinga1_service_status_all = icinga1.get_servicestatus_by_host()

    if hostname:
        icinga1_service_status_all = {hostname: icinga1_service_status_all[hostname]}

    icinga2_hosts = icinga2.get_hosts_dict().keys()
    if hostname:
        icinga2_hosts = [hostname]
    logger.info("Got {} hosts from Icinga2 API".format(len(icinga2_hosts)))

    diff = {}
    logger.info("Retrieving Icinga2 services from API")
    icinga2_services_all = icinga2.get_services_by_hostname()
    icinga2_services_count = sum(
        [len(icinga2_services_all[key]) for key in icinga2_services_all.keys()])
    logger.info("Got {} services from Icinga2 API".format(icinga2_services_count))
    total_diff = 0

    if output:
        f = open(output, 'w')
    else:
        f = sys.stdout

    for icinga2_hostname in icinga2_hosts:
        icinga1_services = icinga1_services_all[icinga2_hostname]
        icinga1_service_states = icinga1_service_status_all[icinga2_hostname]
        icinga2_services = icinga2_services_all[icinga2_hostname]

        # Filter out nrpe checks on Icinga2
        icinga2_services = [service for service in icinga2_services
                            if service['attrs']['name'] != 'nrpe-health']

        # compare extracted check commands
        icinga1_check_commands = [service['check_command_extracted']
                                  for service in icinga1_services]
        icinga2_check_commands = [service['check_command_extracted']
                                  for service in icinga2_services]

        # Check services missing by using extracted check_command as key
        icinga1_missing_icinga2 = \
            [check_command for check_command in icinga1_check_commands
             if check_command not in icinga2_check_commands]

        # Filter checks with same comment
        for icinga2_comment in [ndict(service)['attrs']['vars']['comment']
                                for service in icinga2_services]:
            try:
                icinga1_missing_icinga2.remove(icinga2_comment)
            except ValueError:
                pass

        # Compare notification state if service exists in both systems
        notification_states = {}
        nosla_diff = {}
        notesurl_diff = {}

        for check_command in icinga1_check_commands + icinga2_check_commands:
            service_icinga1 = [service for service in icinga1_services
                               if service['check_command_extracted'] == check_command]
            service_icinga2 = [service for service in icinga2_services
                               if service['check_command_extracted'] == check_command]

            if service_icinga1 and service_icinga2:

                icinga1_description = service_icinga1[0]['service_description']
                icinga1_check_command = service_icinga1[0]['check_command']
                key = '{} - {}'.format(icinga1_check_command, icinga1_description)

                # Use Icinga1 enable_notifications from state if exists, otherwise from config
                icinga1_state = [
                    state for state in icinga1_service_states
                    if state['check_command'] == icinga1_check_command
                    and state['service_description'] == icinga1_description
                ]
                if icinga1_state:
                    icinga1_notifications_enabled = \
                        icinga1_state[0]['notifications_enabled'] == '1'
                else:
                    icinga1_notifications_enabled = service_icinga1[0]['enable_notifications']

                # If state was modified at runtime, use original state from config
                try:
                    icinga2_notifications_enabled = service_icinga2[0]['attrs']['original_attributes']['enable_notifications']
                except KeyError:
                    icinga2_notifications_enabled = service_icinga2[0]['attrs']['enable_notifications']

                if icinga1_notifications_enabled != icinga2_notifications_enabled:
                    notification_states[key] = (icinga1_notifications_enabled,
                                                icinga2_notifications_enabled)

                # compare sla
                icinga1_nosla = service_icinga1[0].get('notes', False) == 'no-sla'
                icinga2_nosla = False
                try:
                    icinga2_nosla = service_icinga2[0]['attrs']['vars']['nosla']
                except:
                    pass
                if icinga1_nosla != icinga2_nosla:
                    nosla_diff[key] = (icinga1_nosla, icinga2_nosla)

                # compare notes url. no diff if confluence entry is in Icinga2
                icinga1_notes = service_icinga1[0].get('notes_url', '')
                icinga2_notes = service_icinga2[0]['attrs']['notes_url']

        # Write results to file
        if icinga1_missing_icinga2 or notification_states or nosla_diff:
            f.write('\n' + icinga2_hostname + '\n')
            diff[icinga2_hostname] = {}
            diff[icinga2_hostname]['host_name'] = icinga2_hostname

            if icinga1_missing_icinga2:
                diff[icinga2_hostname]['icinga1_missing_icinga2'] = icinga1_missing_icinga2
                f.write("Icinga1 services missing in Icinga2:\n")
                f.writelines([cmd + '\n' for cmd in icinga1_missing_icinga2])
                f.write('\n')

            if notification_states:
                f.write("Different notification states:\n")
                diff[icinga2_hostname]['notification_states'] = []
                for key in notification_states:
                    diff[icinga2_hostname]['notification_states'].extend({
                        'command': key,
                        'icinga1': notification_states[key][0],
                        'icinga2': notification_states[key][1]
                    })
                    f.write("Service: {0}, Icinga1: {1}, Icinga2: {2}\n"
                            .format(key,
                                    notification_states[key][0],
                                    notification_states[key][1]))
            if nosla_diff:
                f.write("Different SLA:\n")
                diff[icinga2_hostname]['nosla_diff'] = []
                for key in nosla_diff:
                    diff[icinga2_hostname]['nosla_diff'].extend({
                        'command': key,
                        'icinga1': nosla_diff[key][0],
                        'icinga2': nosla_diff[key][1]
                    })
                    f.write("Service: {0}, Icinga1: {1}, Icinga2: {2}\n"
                            .format(key,
                                    nosla_diff[key][0],
                                    nosla_diff[key][1]))

            if notesurl_diff:
                f.write("Different notes_url:\n")
                diff[icinga2_hostname]['notesurl_diff'] = []
                for key in notesurl_diff:
                    diff[icinga2_hostname]['notesurl_diff'].extend({
                        'command': key,
                        'icinga1': notesurl_diff[key][0],
                        'icinga2': notesurl_diff[key][1]
                    })
                    f.write("Service: {0}, Icinga1: {1}, Icinga2: {2}\n"
                            .format(key,
                                    notesurl_diff[key][0],
                                    notesurl_diff[key][1]))

            total_diff += len(icinga1_missing_icinga2 +
                              list(notification_states.keys()))

    logger.info('Found {} service differences'.format(total_diff))

    if output:
        with open(output + '.json', 'w') as jsonfile:
            logger.info("Wrote JSON file: {}".format(jsonfile.name))
            json.dump(diff, jsonfile)
    return diff


def compare_services_manual(hostname=None, icinga1=Icinga1Config(), icinga2=Icinga2Config()):
    """
    Compare services that cannot be diffed since their check commands are ambiguous.


    :param hostname:
    :param icinga1:
    :param icinga2:
    :return:
    """
    if hostname:
        icinga1_services_all = {hostname: icinga1.get_services(hostname=hostname)}
        icinga2_hostnames = [hostname]
        icinga2_services_all = {hostname: icinga2.get_services(host_name=hostname)}
    else:
        icinga1_services_all = icinga1.get_services_by_hostname()
        icinga2_hostnames = icinga2.get_hosts_dict().keys()
        icinga2_services_all = icinga2.get_services_by_hostname()

    for hostname in icinga2_hostnames:
        icinga1_services = icinga1_services_all[hostname]

        # find services with same check command
        check_commands = [service['check_command_extracted'] for service in icinga1_services]
        duplicate_check_commands = [item for item, count in Counter(check_commands).items()
                                    if count > 1]
        if len(duplicate_check_commands):
            print("\n{}: found {} services: [{}]"
                  .format(hostname,
                          len(duplicate_check_commands),
                          ','.join(duplicate_check_commands)))

            icinga1_duplicate_check_cmd_services = [
                service for service in icinga1_services
                if service['check_command_extracted'] in duplicate_check_commands
            ]
            icinga2_services = [
                service for service in icinga2_services_all[hostname]
                if service['check_command_extracted'] in duplicate_check_commands
            ]

            print("Icinga1 - link: {}".format(icinga1.get_url(hostname)))
            for icinga1_service in icinga1_duplicate_check_cmd_services:
                print("\tcheck command: {}; SLA: {}; description: {}"
                      .format(icinga1_service['check_command'],
                              icinga1_service.get('notes', False) == 'no-sla',
                              icinga1_service['service_description']))

            if icinga2_services:
                print("Icinga2 - link: {}".format(icinga2.get_url(hostname)))
            for icinga2_service in icinga2_services:
                icinga2_nosla = False
                try:
                    icinga2_nosla = icinga2_service['attrs']['vars']['nosla']
                except:
                    pass
                print("\textracted check command: {}; SLA: {}; display name: {}"
                      .format(icinga2_service['check_command_extracted'],
                              icinga2_nosla,
                              icinga2_service['attrs']['display_name']))


def compare_downtimes(icinga1=Icinga1Config(), icinga2=Icinga2Config()):
    """
    List all downtimes of Icinga1/2, ordered per host

    :param icinga1: Icinga1Config
    :param icinga2: Icinga2Config
    :return:
    """
    output = sys.stdout

    sort_by = 'start_time'
    icinga1_downtimes = \
        sorted(icinga1.hostdowntimes + icinga1.servicedowntimes, key=lambda x: x[sort_by])
    icinga2_downtimes = sorted(icinga2.get_downtimes(), key=lambda x: x['attrs'][sort_by])

    icinga1_hosts = [downtime['host_name'] for downtime in icinga1_downtimes]
    icinga2_hosts = [downtime['attrs']['host_name'] for downtime in icinga2_downtimes]

    for host in set(icinga1_hosts + icinga2_hosts):
        downtimes_1 = [downtime for downtime in icinga1_downtimes
                       if downtime['host_name'] == host]
        downtimes_2 = [downtime for downtime in icinga2_downtimes
                       if downtime['attrs']['host_name'] == host]

        if downtimes_1 or downtimes_2:
            output.write(host + '\n')

        if downtimes_1:
            output.write("Icinga1:\n")
            for downtime in downtimes_1:
                start_time_stamp = datetime.utcfromtimestamp(int(downtime['start_time']))
                end_time_stamp = datetime.utcfromtimestamp(int(downtime['start_time']))
                output.write("Comment: {}, Start: {}, End: {}\n"
                             .format(downtime['comment'],
                                     format_date(start_time_stamp),
                                     format_date(end_time_stamp)))
            output.write('\n')

        if downtimes_2:
            output.write("Icinga2:\n")
            for downtime in downtimes_2:
                start_time_stamp = datetime.utcfromtimestamp(int(downtime['attrs']['start_time']))
                end_time_stamp = datetime.utcfromtimestamp(int(downtime['attrs']['start_time']))
                output.write("Comment: {}, Start: {}, End: {}\n"
                             .format(downtime['attrs']['comment'],
                                     format_date(start_time_stamp),
                                     format_date(end_time_stamp)))
            output.write('\n')


def compare_contacts(icinga1=Icinga1Config(), icinga2=Icinga2Config()):
    """
    Compare contacts.

    - check if emails from Icinga1 are existing in Icinga2
    - check if emails and phone numbers (=pager) are correct
    - check if hosts/services have been assigned the same contacts
    :param icinga1: Icinga1Config
    :param icinga2: Icinga2Config
    :return: compare result
    """
    diff = defaultdict(list)
    icinga1_contacts = icinga1.contacts
    icinga2_contacts = icinga2.get_users()

    for icinga1_contact in icinga1_contacts:
        icinga2_contact = [icinga2_contact for icinga2_contact in icinga2_contacts
                           if icinga2_contact['attrs']['name'] == icinga1_contact['contact_name']]
        if not icinga2_contact:
            print("Contact missing in Icinga2: alias:'{}', contact_name:'{}', email:'{}'"
                  .format(icinga1_contact.get('alias', ''), icinga1_contact['contact_name'],
                          icinga1_contact.get('email', '')))

        if icinga2_contact and 'pager' in icinga1_contact.keys():
            icinga2_contact = icinga2_contact[0]
            icinga1_pager = re.sub(r'^00', '', icinga1_contact['pager'])
            icinga2_pager = icinga2_contact['attrs']['pager']

            if icinga1_pager != icinga2_pager:
                print("Wrong pager information for {}. Icinga1: {}, Icinga2: {}"
                      .format(icinga1_contact['contact_name'], icinga1_pager, icinga2_pager))
                diff['wrong_pager'].append(
                    (icinga1_contact['contact_name'], icinga1_pager, icinga2_pager))

            icinga1_mail = icinga1_contact.get('email', None)
            icinga2_mail = ndict(icinga2_contact)['attrs']['email']

            if icinga1_mail and icinga1_mail != icinga2_mail:
                print("Wrong email information for {}. Icinga1: {}, Icinga2: {}"
                      .format(icinga1_contact['contact_name'], icinga1_mail, icinga2_mail))

                diff['wrong_email'].append(
                    (icinga1_contact['contact_name'], icinga1_mail, icinga2_mail))
    return diff


def compare_service_contacts(icinga1=Icinga1Config(), icinga2=Icinga2Config(), hostname=None):
    """
    Check if service contacts have been migrated correctly

    :param icinga1: Icinga1Config
    :param icinga2: Icinga2Config
    :param hostname: hostname
    :return:
    """
    icinga1_services = icinga1.get_services(hostname)
    icinga2_services = icinga2.get_services_by_hostname(host_name=hostname)
    icinga2_service_notifications = icinga2.get_service_notification_contacts(hostname)

    icinga2_contact_excludes = []

    diff = []

    services_iterator = icinga1_services
    if not hostname:
        bar = progressbar.ProgressBar()
        services_iterator = bar(services_iterator)

    for icinga1_service in services_iterator:
        service_name = "{}!{}".format(
            icinga1_service['host_name'], icinga1_service['check_command_extracted'])

        icinga1_contacts = []
        if icinga1_service.get('contacts'):
            icinga1_contacts = sorted([
                contact.strip() for contact in icinga1_service.get('contacts').split(',')
            ])

        icinga2_service = [
            _ for _ in icinga2_services.get(icinga1_service['host_name'], [])
            if _['check_command_extracted'] == icinga1_service['check_command_extracted']
            or ndict(_)['attrs']['vars']['comment'] == icinga1_service.get('check_command')
        ]

        if icinga2_service:
            icinga2_service = icinga2_service[0]
            key = '{}!{}'.format(icinga1_service['host_name'], icinga2_service['attrs']['name'])

            if key in icinga2_service_notifications:
                service_notifications = icinga2_service_notifications[key]
                icinga2_contacts = [
                    user['name'] for user in service_notifications['users']
                    if user['name'] not in icinga2_contact_excludes]
                icinga2_contacts = sorted(list(set(icinga2_contacts)))
            else:
                icinga2_contacts = []

            if icinga1_contacts != ['dummy'] and icinga1_contacts != icinga2_contacts:
                print("Different notify users for service: {}. Icinga1:{}, Icinga2: {}"
                      .format(service_name, icinga1_contacts, icinga2_contacts))
                logger.debug("{}".format(icinga1_service))
                logger.debug("{}".format(icinga2_service))

            if icinga1_service.get('contacts') == 'dummy':
                # Skip if notifications in Icinga2 are disabled
                if icinga1_service['contacts'] == 'dummy' \
                        and icinga1_service['contact_groups'] == 'dummy' \
                        and not icinga2_service['attrs']['enable_notifications']:
                    continue

                diff.append((icinga1_service['host_name'],
                             icinga1_service['check_command_extracted']))
                print("Wrong notification settings for service: {}".format(service_name))
        else:
            logger.warning("Service missing in Icinga2: {}".format(service_name))
    return diff


def compare_acknowledged_problems(output=None, icinga1=Icinga1Config(),
                                  icinga2=Icinga2Config()):
    """
    List all acknowledged problems per host as JSON result

    :param output:
    :param icinga1: Icinga1Config
    :param icinga2: Icinga2Config
    :return:
    """
    icinga1_acks = [status for status in icinga1.status
                    if status.get('problem_has_been_acknowledged', '0') == '1']

    icinga2_acks = icinga2.get_acknowledgements()

    all_hosts = [ack['host_name'] for ack in icinga1_acks] + \
                [status['attrs']['host_name'] for status in icinga2_acks]

    if output:
        f = open(output, 'w')
    else:
        f = sys.stdout

    for host in set(all_hosts):
        acks_1 = [ack for ack in icinga1_acks if ack['host_name'] == host]
        acks_2 = [ack for ack in icinga2_acks if ack['attrs']['host_name'] == host]
        if acks_1 or acks_2:
            f.write(host + '\n')

        if acks_1:
            f.write("Icinga1:\n")
            for ack in acks_1:
                f.write(json.dumps(ack, indent=4))
            f.write('\n')

        if acks_2:
            f.write("Icinga2:\n")
            for ack in acks_2:
                f.write(json.dumps(ack, indent=4))
            f.write('\n')


def pretty_print_services(stream=sys.stdout, hostname=None, icinga1=Icinga1Config(),
                          icinga2=Icinga2Config()):
    """
    Pretty print all services of Icinga1 and Icinga2.

    :param stream: file handle, leave empty to print
    :param hostname: hostname
    :param icinga1: Icinga1Config
    :param icinga2: Icinga2Config
    :return:
    """
    if hostname:
        services_1_all = icinga1.get_services_by_hostname(host_name=hostname)
        services_2_all = icinga2.get_services_by_hostname(host_name=hostname)
    else:
        services_1_all = icinga1.get_services_by_hostname()
        services_2_all = icinga2.get_services_by_hostname()

    hostnames = [hostname] if hostname else list(services_1_all.keys())

    for hostname in hostnames:
        print(hostname, file=stream)

        print('  Icinga1:', file=stream)
        for service in services_1_all.get(hostname, []):
            print('    ' + service['check_command_extracted'] + ':', file=stream)
            pretty_service = yaml.dump(service, None, default_flow_style=False)
            print(textwrap.indent(pretty_service, '      '), file=stream)

        print('  Icinga2:', file=stream)
        for service in services_2_all.get(hostname, []):
            print('    ' + service['check_command_extracted'] + ':', file=stream)
            pretty_service = yaml.dump(service, None, default_flow_style=False)
            print(textwrap.indent(pretty_service, '      '), file=stream)
