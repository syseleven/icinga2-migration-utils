import logging

from icinga2api.client import Icinga2ApiException
from icinga_migration_utils.icinga1.icinga1 import Icinga1Config
from icinga_migration_utils.icinga2.icinga2 import Icinga2Config
from icinga_migration_utils.migrate import MIGRATION_COMMENT_SUFFIX
from icinga_migration_utils.utils import ndict

logger = logging.getLogger(__name__)


def migrate_host_downtimes(simulate=True, suffix=MIGRATION_COMMENT_SUFFIX,
                           hostname=None):
    """
    Migrate host downtimes

    :param simulate: don't send requests to API
    :param suffix: downtime comment suffix
    :type simulate: bool
    :param hostname: hostname
    :return:
    """
    icinga1 = Icinga1Config()
    icinga2 = Icinga2Config()
    icinga2_hosts = icinga2.get_hosts_dict()

    downtimes = [dt for dt in icinga1.hostdowntimes
                 if 'daily' not in dt['comment'].lower()
                 and 'weekly' not in dt['comment'].lower()]

    if hostname:
        downtimes = [downtime for downtime in downtimes if downtime['host_name'] == hostname]

    logger.info("Got {} host downtimes to migrate.".format(len(downtimes)))
    migrate_count = 0

    for downtime in downtimes:
        dt_hostname = downtime['host_name']
        author = downtime['author']
        comment = downtime['comment'] + suffix
        start_time = int(downtime['start_time'])
        end_time = int(downtime['end_time'])
        duration = int(downtime['duration'])
        fixed = True if downtime['fixed'] == '1' else False

        if dt_hostname not in icinga2_hosts:
            logger.error("Host '{}' not in Icinga2, skipping".format(dt_hostname))
            continue

        downtime_filter = {
            'host_name': dt_hostname,
            'author': author,
            'comment': comment,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'fixed': fixed,
        }

        try:
            downtime_exists = icinga2.get_downtimes(**downtime_filter) != []
        except Icinga2ApiException:
            downtime_exists = False

        if downtime_exists:
            logger.warning("Downtime {} already exists, skipping.".format(downtime_filter))
        elif not simulate:
            migrate_count += 1
            icinga2.schedule_host_downtime(**downtime_filter)

    logger.info("Migrated {} host downtimes".format(migrate_count))


def migrate_service_downtimes(simulate=True, suffix=MIGRATION_COMMENT_SUFFIX, hostname=None):
    """
    Migrate service downtimes

    :param simulate: don't send requests to API
    :param suffix: downtime comment suffix
    :type simulate: bool
    :param hostname: hostname
    :return:
    """
    icinga1 = Icinga1Config()
    icinga2 = Icinga2Config()
    icinga2_hosts = icinga2.get_hosts_dict()

    icinga1_services = icinga1.get_services_by_hostname()
    icinga2_services = icinga2.get_services_by_hostname()

    downtimes = [dt for dt in icinga1.servicedowntimes
                 if 'daily' not in dt['comment'].lower()
                 and 'weekly' not in dt['comment'].lower()]

    if hostname:
        downtimes = [downtime for downtime in downtimes if downtime['host_name'] == hostname]

    logger.info("Got {} service downtimes to migrate.".format(len(downtimes)))
    migrate_count = 0

    for downtime in downtimes:
        dt_hostname = downtime['host_name']
        author = downtime['author']
        comment = downtime['comment'] + suffix
        start_time = int(downtime['start_time'])
        end_time = int(downtime['end_time'])
        duration = int(downtime['duration'])
        fixed = True if downtime['fixed'] == '1' else False

        if dt_hostname not in icinga2_hosts:
            logger.error("Host '{}' not in Icinga2, skipping".format(dt_hostname))
            continue

        service_icinga1 = [
            service for service in icinga1_services[dt_hostname]
            if service['service_description'] == downtime['service_description']][0]

        services_icinga2 = [
            service for service in icinga2_services[dt_hostname]
            if service['check_command_extracted'] == service_icinga1['check_command_extracted']
            or ndict(service)['attrs']['vars']['comment'] == service_icinga1.get('check_command')
        ]
        if not services_icinga2:
            logger.error("Service not found: {}!{}"
                         .format(dt_hostname, downtime['service_description']))
            continue
        else:
            if len(services_icinga2) > 1:
                logger.error(
                    "AMBIGUOUS - host: {}, downtime service description: '{}'".format(
                        dt_hostname,
                        downtime['service_description']
                    )
                )
                for service in services_icinga2:
                    logger.error(
                        "AMBIGUOUS - icinga2: service_name:'{}', display_name:'{}', check_command:'{}', check_command_extracted:'{}'".format(
                        service['name'], service['attrs']['display_name'], service['attrs']['check_command'], service['check_command_extracted'])
                    )
            service_icinga2 = services_icinga2[0]
            logger.debug("Found service: {}".format(service_icinga2))

        service_name = service_icinga2['attrs']['name']

        # query service_name
        downtime_filter = {
            'host_name': dt_hostname,
            'service_name': service_name,
            'downtime_author': author,
            'downtime_comment': comment,
            'downtime_start_time': start_time,
            'downtime_end_time': end_time,
            'downtime_duration': duration,
            'downtime_fixed': fixed,
        }
        try:
            downtime_exists = icinga2.get_downtimes(**downtime_filter) != []
        except Icinga2ApiException:
            downtime_exists = False
        if downtime_exists:
            logger.warning("Downtime {} already exists, skipping.".format(downtime_filter))
        elif not simulate:
            migrate_count += 1
            icinga2.schedule_service_downtime(**downtime_filter)
        else:
            logger.warning("Would migrate downtime: {}".format(downtime_filter))

    logger.info("Migrated {} service downtimes".format(migrate_count))


def clean_migrated_downtimes(suffix=MIGRATION_COMMENT_SUFFIX):
    """
    Remove all downtimes that have been migrated
    """
    icinga2 = Icinga2Config()
    response = icinga2.client.actions.remove_downtime(
        object_type='Downtime',
        filter=r'match("*{}", downtime.comment)'.format(suffix)
    )
    logger.debug("Got response: {}".format(response))

    if 'results' in response:
        logger.info("Removed {} services".format(len(response['results'])))
