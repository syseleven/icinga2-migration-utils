import os

from icinga_migration_utils.icinga1.icinga1 import Icinga1Config, ObjectType

sample_objects = os.path.join(
    os.path.dirname(__file__), 'fixtures', 'objects_small_monitoring01.cache')
sample_objects_broken = os.path.join(
    os.path.dirname(__file__), 'fixtures', 'objects_broken_contact_monitoring01.cache')
sample_status = os.path.join(
    os.path.dirname(__file__), 'fixtures', 'status_monitoring01.cache')


def test_object_parser():
    config = Icinga1Config(objects_files=sample_objects, status_files=sample_status)
    assert config.objects[0] == {
        'object_type': 'host',
        'host_name': 'awesome.host',
        'address': '10.3.147.5',
        'monitoring_source': 'monitoring01',
    }
    assert config.objects[1] == {
        'object_type': 'service',
        'host_name': 'awesome.host',
        'service_description': 'Zabbix Agent TCP',
        'monitoring_source': 'monitoring01'
    }


def test_object_broken_contact_parser():
    # Cache file with empty contact value should be parsed correctly
    config = Icinga1Config(objects_files=sample_objects_broken, status_files=sample_status)
    assert config.objects[0]['contacts'] is None
    assert config.objects[0]['contact_groups'] is None


def test_status_parser():
    expected = {
        'author': 'Jon Doe',
        'comment': '74864',
        'downtime_id': '18597',
        'duration': '157766400',
        'end_time': '1633859009',
        'entry_time': '1476092629',
        'fixed': '1',
        'host_name': 'awesome.host',
        'is_in_effect': '1',
        'object_type': 'hostdowntime',
        'start_time': '1476092609',
        'trigger_time': '1476092629',
        'triggered_by': '0',
        'monitoring_source': 'monitoring01'
    }
    config = Icinga1Config(objects_files=sample_objects, status_files=sample_status)
    assert expected in config.status


def test_downtimes():
    config = Icinga1Config(objects_files=sample_objects, status_files=sample_status)
    downtime = config.hostdowntimes[0]

    config = Icinga1Config(objects_files=sample_objects, status_files=sample_status)
    downtime = config.servicedowntimes[0]


def test_icinga1_queries():
    # Test getting correct results when querying Icinga1 for multiple key-value pairs
    config = Icinga1Config()
    service1 = {
        'host_name': 'host1',
        'object_type': ObjectType.SERVICE,
        'check_command': 'test_check',
        'notifications_enabled': True
    }
    service2 = {
        'host_name': 'host2',
        'object_type': ObjectType.SERVICE,
        'check_command': 'test_check',
        'notifications_enabled': True
    }
    service3 = {
        'host_name': 'host2',
        'object_type': ObjectType.SERVICE,
        'check_command': 'test_check2',
        'notifications_enabled': True
    }
    config._objects = [service1, service2, service3]
    result = config.get_services(host_name=service1['host_name'])
    assert len(result) == 1
    assert result[0] == service1

    result = config.get_services(host_name='host2', check_command=service3['check_command'])
    assert len(result) == 1
    assert result[0] == service3
