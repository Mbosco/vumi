# -*- test-case-name: vumi.tests.test_servicemaker -*-

import sys
import warnings

import yaml
from zope.interface import implements
from twisted.python import usage
from twisted.application.service import IServiceMaker
from twisted.plugin import IPlugin

from vumi.service import WorkerCreator
from vumi.utils import load_class_by_string
from vumi.errors import VumiError
from vumi.sentry import SentryLoggerService


def overlay_configs(*configs):
    """Non-recursively overlay a set of configuration dictionaries"""
    config = {}

    for overlay in configs:
        config.update(overlay)

    return config


def filter_null_values(config):
    """Remove keys with None values from a dictionary."""
    return dict(item for item in config.iteritems() if item[1] is not None)


def read_yaml_config(config_file, optional=True):
    """Parse an (usually) optional YAML config file."""
    if optional and config_file is None:
        return {}
    with file(config_file, 'r') as stream:
        # Assume we get a dict out of this.
        return yaml.safe_load(stream)


class VumiOptions(usage.Options):
    """
    Options global to everything vumi.
    """
    optParameters = [
        ["hostname", None, None, "AMQP broker (*)"],
        ["port", None, None, "AMQP port (*)", int],
        ["username", None, None, "AMQP username (*)"],
        ["password", None, None, "AMQP password (*)"],
        ["vhost", None, None, "AMQP virtual host (*)"],
        ["specfile", None, None, "AMQP spec file (*)"],
        ["sentry", None, None, "Sentry DSN (*)"],
        ["vumi-config", None, None,
         "YAML config file for setting core vumi options (any command-line"
         " parameter marked with an asterisk)"],
    ]

    default_vumi_options = {
        "hostname": "127.0.0.1",
        "port": 5672,
        "username": "vumi",
        "password": "vumi",
        "vhost": "/develop",
        "specfile": "amqp-spec-0-8.xml",
        "sentry": None,
        }

    def get_vumi_options(self):
        # We don't want these to get in the way later.
        vumi_option_params = {}
        for opt in (i[0] for i in VumiOptions.optParameters):
            vumi_option_params[opt] = self.pop(opt)

        config_file = vumi_option_params.pop('vumi-config')

        # non-recursive overlay is safe because vumi options are
        # all simple key-value pairs
        return overlay_configs(
            self.default_vumi_options,
            read_yaml_config(config_file),
            filter_null_values(vumi_option_params))

    def postOptions(self):
        self.vumi_options = self.get_vumi_options()


class StartWorkerOptions(VumiOptions):
    """
    Options to the vumi_worker twistd plugin.
    """

    optFlags = [
        ["worker-help", None,
         "Print out a usage message for the worker-class and exit"],
        ]

    optParameters = [
        ["worker-class", None, None, "Class of a worker to start"],
        ["worker_class", None, None, "Deprecated. See --worker-class instead"],
        ["config", None, None, "YAML config file for worker configuration"
         " options"],
    ]

    longdesc = """Launch an instance of a vumi worker process."""

    def __init__(self):
        VumiOptions.__init__(self)
        self.set_options = {}

    def opt_set_option(self, keyvalue):
        """Set a worker configuration option (overrides values
        specified in the file passed to --config)."""
        key, _sep, value = keyvalue.partition(':')
        self.set_options[key] = value

    def exit(self):
        # So we can stub it out in tests.
        sys.exit(0)

    def do_worker_help(self):
        """Print out a usage message for the worker-class and exit"""
        worker_class = load_class_by_string(self.worker_class)
        print worker_class.__doc__
        self.exit()

    def get_worker_class(self):
        worker_class = self.opts.pop('worker-class')
        depr_worker_class = self.opts.pop('worker_class')

        if depr_worker_class is not None:
            warnings.warn("The --worker_class option is deprecated since"
                          " Vumi 0.3. Please use --worker-class instead.",
                          category=DeprecationWarning)
            if worker_class is None:
                worker_class = depr_worker_class

        if worker_class is None:
            raise VumiError("please specify --worker-class")

        return worker_class

    def get_worker_config(self):
        config_file = self.opts.pop('config')

        # non-recursive overlay is safe because set_options
        # can only contain simple key-value pairs.
        return overlay_configs(
            read_yaml_config(config_file),
            self.set_options)

    def postOptions(self):
        VumiOptions.postOptions(self)

        self.worker_class = self.get_worker_class()

        if self.opts.pop('worker-help'):
            self.do_worker_help()

        self.worker_config = self.get_worker_config()


class VumiWorkerServiceMaker(object):
    implements(IServiceMaker, IPlugin)
    # the name of our plugin, this will be the subcommand for twistd
    # e.g. $ twistd -n vumi_worker --option1= ...
    tapname = "vumi_worker"
    # description, also for twistd
    description = "Start a Vumi worker"
    # what command line options does this service expose
    options = StartWorkerOptions

    def makeService(self, options):
        sentry_dsn = options.vumi_options.pop('sentry', None)

        worker_creator = WorkerCreator(options.vumi_options)
        worker = worker_creator.create_worker(options.worker_class,
                                              options.worker_config)

        if sentry_dsn is not None:
            sentry_service = SentryLoggerService(sentry_dsn)
            worker.addService(sentry_service)

        return worker


class DeprecatedStartWorkerServiceMaker(VumiWorkerServiceMaker):
    tapname = "start_worker"
    description = "Deprecated copy of vumi_worker. Use vumi_worker instead."
