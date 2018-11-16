import logging

from icinga_migration_utils.icinga1.icinga1 import Icinga1Config
from icinga_migration_utils.icinga2.icinga2 import Icinga2Config
from icinga_migration_utils.migrate import MIGRATION_COMMENT_SUFFIX
from icinga_migration_utils.utils import ndict

logger = logging.getLogger(__name__)


def migrate_service_acknowledgements(simulate=True, suffix=MIGRATION_COMMENT_SUFFIX,
                                     hostname=None):
    """
    Migrate all service acknowledgements or only service acknowledgements
    related to one hostname.

    :param simulate: simulate, don't write
    :type simulate: bool
    :param suffix: Suffix to append to acknowledgements to distinguish from existing acks
    :type suffix: str
    :param hostname: hostname to migrate acks for
    :type hostname: str
    :return:
    """
    result = []
    icinga1 = Icinga1Config()
    icinga2 = Icinga2Config()

    icinga1_services = icinga1.get_services_by_hostname()
    icinga2_services_all = icinga2.get_services_by_hostname()
    icinga2_hosts = icinga2.get_hosts_dict()

    migrate_count = 0

    if hostname:
        icinga1_acks = [ack for ack in icinga1.service_acknowledgements
                        if ack['host_name'] == hostname]
    else:
        icinga1_acks = [ack for ack in icinga1.service_acknowledgements]

    for ack in icinga1_acks:
        ack_hostname = ack['host_name']
        if ack_hostname not in icinga2_hosts:
            logger.error("Host not available in Icinga2: '{}'".format(ack_hostname))
            continue

        services_icinga1 = \
            [service for service in icinga1_services[ack_hostname]
             if service.get('service_description', None) == ack['service_description']]
        assert len(services_icinga1) == 1
        service_icinga1 = services_icinga1[0]

        services_icinga2 = [
            service for service in icinga2_services_all[ack_hostname]
            if service['check_command_extracted'] == service_icinga1['check_command_extracted']
            or ndict(service)['attrs']['vars']['comment'] == service_icinga1['check_command_extracted']
        ]
        if not services_icinga2:
            logger.error("Could not find Service: {}!{}".format(
                ack_hostname, service_icinga1['check_command_extracted']))
        else:
            icinga2_service_name = services_icinga2[0]['attrs']['name']
            if simulate:
                logger.info("Would acknowledge service: {}!{}"
                            .format(ack_hostname, service_icinga1['check_command_extracted']))
            else:

                if icinga2.get_acknowledgements(
                        host_name=ack_hostname,
                        author=ack['author'],
                        service_name=icinga2_service_name,
                        comment=ack['comment_data'] + suffix):
                    logger.warning("Acknowledgement {} already exists - skipping".format(ack))
                else:
                    result = icinga2.acknowledge_service(
                        host_name=ack_hostname,
                        service_name=icinga2_service_name,
                        author=ack['author'],
                        comment=ack['comment_data'] + suffix
                    )
                    if result:
                        migrate_count += 1
    logger.info("Migrated {} service acknowledgements".format(migrate_count))
    return result


def migrate_host_acknowledgements(simulate=True, suffix=MIGRATION_COMMENT_SUFFIX,
                                  hostname=None):
    """
    Migrate all host acknowledgements or just only acks related to one hostname.

    :param simulate: simulate, don't write
    :type simulate: bool
    :param suffix: Suffix to append to acknowledgements to distinguish from existing acks
    :type suffix: str
    :param hostname: hostname to migrate acks for
    :type hostname: str
    :return:
    """
    result = []
    icinga1 = Icinga1Config()
    icinga2 = Icinga2Config()
    migrate_count = 0

    if hostname:
        icinga1_host_acks = [
            ack for ack in icinga1.host_acknowledgements
            if ack['host_name'] == hostname
        ]
    else:
        icinga1_host_acks = [ack for ack in icinga1.host_acknowledgements]

    for ack in icinga1_host_acks:
        logger.debug(ack)
        host_name = ack['host_name']

        if simulate:
            logger.info("Would acknowledge host: {}".format(host_name))
        else:
            if icinga2.get_acknowledgements(
                    host_name=host_name,
                    author=ack['author'],
                    comment=ack['comment_data'] + suffix):
                logger.warning("Acknowledgement {} already exists - skipping".format(ack))
            else:
                result = icinga2.acknowledge_host(
                    host_name=host_name,
                    author=ack['author'],
                    comment=ack['comment_data'] + suffix
                )
                if result:
                    migrate_count += 1
    logger.info("Migrated {} host acknowledgements".format(migrate_count))
    return result
