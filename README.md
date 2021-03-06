# Icinga Migration Utilities

Tools to help migration from Icinga 1.x to Icinga 2.x.

These tools are not meant to provide a full solution to perform the Icinga 1/2 migration since
every Icinga setup might be very different from one another.
The code still might contain some places that will not fit your setup.   

Instead, this repository provides some basic tools to get started retrieving and comparing
data between Icinga 1.x and Icinga 2.x.

More information about Icinga: [Icinga Open Source Monitoring](https://www.icinga.com/).  

## Getting Started

### Installation via pip:

```
pip install -r requirements.txt
pip install .
```

### Run tests:

Install pytest and run tests:

```
pip install pytest
pytest
```


## Icinga 1

To get monitoring configuration from an Icinga 1.x installation, Icinga Migration Utilities
parse object cache files and status cache files as generated by Icinga 1.x. 
These files contain the monitoring config as well as the current state (e.g. checks that 
have been disabled at runtime).

When parsing is finished, you can access your configuration items in an object oriented way:
* Hosts
* Host status
* Services
* Service status
* Downtimes
* Acknowledgements
* Contacts

## Icinga 2

Icinga Migration Utilities uses [python-icinga2api](https://github.com/syseleven/python-icinga2api) to communicate with Icinga 2.x Rest API. 

## Icinga 2 - Configuration

For Icinga2 API usage, put a file called .icingadiffrc into your home directory, with the 
following content replaced with your connection details and credentials:

```ini
[icinga2_web]
url = https://$IP_ADDRESS:$PORT/v1
username = $ICINGA2_API_USERNAME
password = $ICINGA2_API_PASSWORD
#ignore_insecure_requests = True  # In case you don't have proper certificates setup
```

## Authors

* Ingo Fischer

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details

## Acknowledgements

* [fmnisme](https://github.com/fmnisme) (original python-icinga2api author)
* [Tobias von der Krone](https://github.com/tobiasvdk) (python-icinga2api fork with some enhancements)

