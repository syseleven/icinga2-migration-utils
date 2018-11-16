import logging

from icinga_migration_utils.icinga1.icinga1 import Icinga1Config
from icinga_migration_utils.icinga2.icinga2 import Icinga2Config
from icinga_migration_utils.migrate import MIGRATION_COMMENT_SUFFIX
from icinga_migration_utils.utils import pretty_print_dict

logger = logging.getLogger(__name__)


def migrate_host_notification_states(simulate=True, suffix=MIGRATION_COMMENT_SUFFIX,
                                     hostname=None):
    """
    Migrate enable_notifications for hosts.
    States are only migrated if host notifications are enabled but host status notifications
    are disabled.

    @param simulate: Simulate (don't perform requests to Icinga2)
    @type simulate: bool
    @param suffix: Suffix to append to Icinga2 notes
    @type suffix: str
    @param hostname: Host (leave empty for all hosts)
    @type hostname: str

    :return:
    """
    icinga1 = Icinga1Config()
    icinga2 = Icinga2Config()

    icinga2_hosts = [host['name'] for host in icinga2.get_hosts()]

    icinga1_host_dict = icinga1.get_hosts_dict()

    if hostname:
        hostnames = [hostname]
    else:
        hostnames = icinga1_host_dict.keys()

    icinga1_status_dict = icinga1.get_hoststatus_by_host()

    for hostname in hostnames:
        if hostname not in icinga1_host_dict:
            logger.error("Host {} not available in Icinga1".format(hostname))
        elif hostname not in icinga2_hosts:
            logger.error("Host {} not available in Icinga2".format(hostname))
        else:
            host_enabled = icinga1_host_dict[hostname]['notifications_enabled'] == '1'
            host_status_enabled = icinga1_status_dict[hostname]['notifications_enabled'] == '1'

            if host_enabled and not host_status_enabled:
                logger.debug(icinga1_status_dict[hostname])
                logger.info("Disabling notifications for host: {}".format(hostname))
                if not simulate:
                    try:
                        response = icinga2.set_host_notifications(
                            hostname, False,
                            notes='Migrated notification state from Icinga1' + suffix)
                        logger.debug(response)
                    except Exception as error:
                        logger.error("Could not migrate host notification state for host {}. "
                                     "Error: {}"
                                     .format(hostname, error))

    return icinga1_status_dict


def migrate_service_notification_states(simulate=True, suffix=MIGRATION_COMMENT_SUFFIX,
                                        hostname=None):
    """
    Migrate enable_notifications for service states.
    Should be run after host notification states have been migrated.

    States are only migrated if:
    * Icinga1 service notifications are enabled but service status notifications are disabled
    * Icinga1 host notifications are enabled
    * Icinga2 service exists
    * Icinga2 service notifications are enabled

    Should be run *after* migrate_host_notification_states

    @param simulate: Simulate (don't perform requests to Icinga2)
    @type simulate: bool
    @param suffix: Suffix to append to Icinga2 notes
    @type suffix: str
    @param hostname: Host (leave empty for all hosts)
    @type hostname: str

    :return:
    """
    icinga1 = Icinga1Config()
    icinga2 = Icinga2Config()

    services_icinga1 = icinga1.get_services_by_hostname()
    services_icinga2 = icinga2.get_services_by_hostname()

    icinga2_hosts = icinga2.get_hosts_dict()

    icinga1_status_dict = icinga1.get_servicestatus_by_host()

    if hostname:
        hostnames = [hostname]
    else:
        hostnames = [host['host_name'] for host in icinga1.get_hosts()]

    count = 0

    for hostname in hostnames:
        if hostname not in icinga2_hosts:
            logger.error("Host not available in Icinga2: '{}'".format(hostname))
            continue
        services = services_icinga1[hostname]
        service_states = icinga1_status_dict[hostname]

        for service in services:
            logger.debug(service['check_command'])
            logger.debug(pretty_print_dict(service, '    '))
            service_state = [state for state in service_states
                             if state['check_command'] == service['check_command']]
            if service_state:
                service_state = service_state[0]
                logger.debug("Got service state:\n{}".format(
                    pretty_print_dict(service_state, '    ')))

                if service['notifications_enabled'] == '1' \
                        and service_state['notifications_enabled'] == '0':

                    icinga2_service = [
                        x for x in services_icinga2[hostname]
                        if x['check_command_extracted'] == service['check_command_extracted']
                    ]
                    if len(icinga2_service) == 1:
                        icinga2_service = icinga2_service[0]
                        service_name = icinga2_service['attrs']['name']
                        if icinga2_service['attrs']['enable_notifications']:
                            logger.debug("{}!{}: disabling service notifications"
                                         .format(hostname, service_name))

                            if not simulate:
                                try:
                                    response = icinga2.set_service_notifications(
                                        hostname,
                                        service_name, False,
                                        notes='Migrated notification state from Icinga1' + suffix)
                                    logger.info("Disabled service notifications for host {}, "
                                                "service {}".format(hostname, service_name))
                                    count += 1
                                    logger.debug(response)
                                except Exception as error:
                                    logger.error("Could not migrate host notification state "
                                                 "for host {}, service {}. Error: {}"
                                                 .format(hostname, service_name, error))
                        else:
                            logger.debug("{}!{}: service notifications already disabled"
                                         .format(hostname, service_name))
                    elif len(icinga2_service) == 0:
                        logger.error("Service {}!{} not found".format(
                            hostname, service['check_command_extracted']))
    logger.info("{} notifications disabled".format(count))
