from setuptools import find_packages, setup


setup(
    name='icinga-migration-utils',
    version='0.0.1',
    description='Utilities to help migration from Icinga 1 to Icinga 2',
    author='Ingo Fischer',
    author_email='ingo.fischer@syseleven.de',
    packages=find_packages(),
    zip_safe=False,
    long_description=open("README.md").read(),
    install_requires=[
        'boltons',
        'click',
        'colorlog',
        'nested_dict',
        'progressbar2',
        'ruamel.yaml',
    ],
    include_package_data=True
)
