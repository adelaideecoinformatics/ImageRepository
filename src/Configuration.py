"""
Configuration for the Image repository
"""


from xml.etree import ElementTree
import sys
import os
import stat
import json
import xmltodict
import argparse
import logging
import signal
from urlparse import urljoin
import urllib
import glob
import ssl
import cStringIO
import re
import datetime
import StringIO
import string
import yaml
import Caches
import ImageNames
import ImageType
import Stores
import swiftclient

from Exceptions import RepositoryError
from Exceptions import RepositoryFailure

args = None
logger = None
error = None
config = None
repo = None

class BaseConfig(yaml.YAMLObject):
    """Base class to encapsulate configuration capability.

    Configuration defaults are set in a subclass's __init__
    Any public component may be overridden by a value in the config file
    Private (ie _xxx) vlaues are untouched and may be used for whatever is desired in the subclasses.
    Only public components can be set from the config file, it is not possible to create new values
    for a config file.

    Class variables that match the public variables of the instance should contain strings that provide short
    descriptions of the configuration variable's use.  These will be appended as comments to the YAML
    dump of the configuration - acting as a self documenting configuration file.
    """

    yaml_tag = u'!Basic tag - should be overridden'

    def __init__(self, config):
        """
        """
        pass

    def _assign_config(self, fields, configuration):
        """Assign the values from the config file to the class variables.

        Recursively traverse the configuration in tandem with the config object and assign
        values as found in the configuration.  Python type checking will avoid the most simple
        of type mismatches, and will catch unknow/incorrect configuration option names.

        :param fields: Instance of a subclass of BaseConfig to which the values will be assigned
        :param configuration: Object containing the configuration values
        """
        if configuration is None:
            return
        for key in configuration.iterkeys():
            if type(fields) is not dict and key in fields.__dict__:
                if key[:2] == "_":
                    continue   # Don't let some smart alec override private values.
                if type(configuration[key]) is dict:
                    try:
                        self._assign_config(fields.__dict__[key], configuration[key])    # This works because the field must be initialised with an instance of the correct type.
                    except (ValueError, AttributeError) as ex:
                        logger.error("Error in config file - no such configuration field: {}".format(key))
                        raise RepositoryError("Error in config file - no such configuration field: {}".format(key))
                else:
                    try:
                        fields.__dict__[key] = configuration[key]
                    except TypeError as ex:
                        logger.error("Error in config file - type mismatch for {} : {}".format(key, configuration))
                        raise RepositoryError("Error in config file - type mismatch for {} : {}".format(key, configuration))
            else:
                try:
                    fields[key] = configuration[key]
                except AttributeError as ex:
                    logger.error("Unknown option in configuration file: {}".format(key))
                    raise RepositoryError("Unknown option in configuration file: {}".format(key))

    def __repr__(self):
        return "String holding fields that matter - should be overriden"
            
    def _parse_yaml(self, config_file_name):
        """Loads a yaml config file and set configuration options from it.

        The file may only contain valid config options.
        Only items already extant in the object to be configured
        can be assigned to, and the types must match those of those items.  
        Default values (those assigned in the class constructor) are overwritten.
        """
        from yaml import safe_load
        try:
            with open(config_file_name) as config_file:
                configuration = safe_load(config_file)
        except IOError as ex:
            logger.exception("Failure in reading config file")
            raise RepositoryError("Failure in reading config file")
        except yaml.YAMLError as ex:
            logger.exception("Failure in parsing config file")
            raise RepositoryError("Failure in parsing config file")
        self._assign_config(self, configuration)
             
    def __str__(self):
#        from yaml import dump as dump
        
#        return string.join(dump(self, indent = 4, default_flow_style = False, width = 1200).split("\\n"), "\n") + '\n'

        return self.yaml_str(self, 0)
        
    @classmethod
    def yaml_str(cls, data, level):
        comment_column = 60
        indent = level * 4
        the_string = ""
        entries = sorted(data.__dict__.keys())
        for entry in entries:
            if not entry.startswith('_'):
                if isinstance(data.__dict__[entry], BaseConfig):
                    comment_str = cls.find_comment(entry, data)
                    padding = max(5, comment_column - (len(entry)) - 2)  # Try to make comments align
                    # Break heirachical config up to ensure we have the top level comment at the start
                    the_string += "{:>{}s}{}: {:>{}}#  {}\n".format('', indent, entry, '', padding, comment_str)
                    the_string += data.__dict__[entry].yaml_str(data.__dict__[entry], level + 1)
                else:
                    comment_str = cls.find_comment(entry, data)
                    data_str = str(data.__dict__[entry] if not isinstance(data.__dict__[entry], str) else "'{}'".format(data.__dict__[entry]))
                    padding = max(5, comment_column - (len(entry) + len(data_str) + 2))  # Try to make comments align
                    the_string += "{:>{}s}{}: {}{:>{}}#  {}\n".format('', indent, entry, data_str,'' , padding, comment_str)
                    
        return the_string
        

    @classmethod
    def find_comment(cls, entry, data):
        if isinstance(cls, BaseConfig):
            return ''
        if entry in cls.__dict__:
            return cls.__dict__[entry]
        else:
            for base in cls.__bases__:
                try:
                    return base.find_comment(entry, data)
                except AttributeError:
                    pass
        return ''

    
    @classmethod
    def to_yaml(cls, dumper, data):
        """Dump a yaml representation of the configuration object and its current values.
        """
        #        return yaml.SequenceNode(tag=u'tag:yaml.org,2002:seq', value=[
        #            yaml.ScalarNode(tag = 'tag:yaml.org,2002:str', value = u"{} : {}".format(entry, str(data.__dict__[entry])))
        #            if not entry.startswith("_") else None for entry in data.__dict__.iterkeys()
        #        ])

        values = []
        for entry in data.__dict__.iterkeys():
            if not entry.startswith('_'):
                values.append( (yaml.ScalarNode(tag = 'tag:yaml.org,2002:str', value = entry),
                                 yaml.ScalarNode(tag= 'tag:yaml.org,2002:str', value = str(data.__dict__[entry]) +
                                                 "  #    " + str(cls.__dict__[entry] if entry in cls.__dict__ else "")))
                )
        return yaml.MappingNode(tag=u'tag:yaml.org,2002:seq', value=values)
                
#        return yaml.MappingNode(tag=u'tag:yaml.org,2002:seq', value=[
#            (yaml.ScalarNode(tag = 'tag:yaml.org,2002:str', value = entry), yaml.ScalarNode(tag= 'tag:yaml.org,2002:str',
#                                                                                            value = str(data.__dict__[entry]) + "  # " + str(data.__dict__[entry])))
#            if not entry.startswith("_") else None for entry in data.__dict__.iterkeys()
#        ])

    
class CacheConfig(BaseConfig):
    """Cache operation configuration
    """

    
    yaml_tag = u'!Cache_Configuration'
    evict_free_threshold = "Fraction of allocation used to begin eviction from cache (real in range (0.0:1.0)"
    evict_hysterysis = "Fraction of store allocation used less than evict threshold to allow ending eviction (real in range (0.0:1.0)"
    priority = "Which object to favour for retention: one of 'newest', 'largest', 'smallest', 'thumbnail'"
    eager_writeback = "Writeback strategy, one of 'eager', 'lazy', 'never'"
    alarm_free_threshold = "Proportion of store allocation free to signal alarm (real in range (0.0:1.0)"
    max_size = "Maximum size of store (bytes), 0 = unlimited (integer)"
    max_elements = "Maximum number of elements to store. 0 = unlimited (integer)"
    next_level = "Next cache down in the heirarchy"
    
    def __init__(self, config):
        super(CacheConfig, self).__init__(config)
        self.evict_free_threshold = 0.2
        self.evict_hysterysis = 0.2
        self.priority = "newest"  # newest, smallest, largest, oldest
        self.eager_writeback = False
        self.alarm_free_threshold = 0.1
        self.max_size = 1 * 1024 * 1024 * 1024 # Gigabytes
        self.max_elements = 1024 * 1024
        self.next_level = None
        self._previous_level = None
        self._assign_config(self, config)

class CredentialsConfig(BaseConfig):
    """Configuration of access credentials used for Nectre
    """
    
    yaml_tag = u"!Nectre_Credentials"
    username = "Owner user of the swift storage (key, value)"
    authurl = "URL of the authentication server (key, value)"
    tenant = "Project name or similar (key, value)"
    tenant_id = "Id string for the project (key, value)"
    password = "Swift access password (key, value)"
    
    def __init__(self, config):
        super(CredentialsConfig, self).__init__(config)
        self.username = ("env", "OS_USERNAME")
        self.tenant = ("env", "OS_TENANT_NAME")
        self.tenant_id = ("env", "OS_TENANT_ID")
        self.authurl = ("env", "OS_AUTH_URL")
        self.password = ("env", "OS_PASSWORD")
        
        self._assign_config(self, config)
        
        self._the_password = self._find_param(self.password)
        self._the_username = self._find_param(self.username)
        self._the_authurl = self._find_param(self.authurl)
        self._the_tenant_name = self._find_param(self.tenant)
        self._the_tenant_id = self._find_param(self.tenant_id)

    def clear_password(self):
        self.password = ""
        
    def _find_param(self, param):
        """Simple way of denoting where a param value may be found.

        :param param: how to find the required parameter
        :type param: tuple 
        :returns: required parameter value or None
        :type returns: string 

        Param is a key value pair (param_name, mechanism)

        mechanism may be one of-
        env:
        Use the specified environment variable to obtain the value

        file:
        Read the value from the specified file name.

        explicit:
        The value here is the value to use.

        """
        if param[1] is None:
            return None
        if param[0] == "env":
            try:
                return os.environ[param[1]]
            except KeyError:
                logger.error("Failure in obtaining credentials parameter from environment variable {}   - no such variable".format(param[1]))
                return None
        elif param[0] == "file":
            with open(param[1]) as the_file:
                result = the_file.read()
            return result
        elif param[0] == "explicit":
            return param[1]
        else:
            logger.error("Failure in obtaining param {} from {}".format(param[0], param[1]))
            raise RepositoryError("Failure in obtaining param {} from {}".format(param[0], param[1]))
    
class SwiftStoreConfig(CacheConfig):
    """Configuration of a Swift store used to hold long-term resilient storage of preserved objects
    """
    
    yaml_tag = u'!Swift_Storage_Configuration'
    credentials = "Credentials needed to access Swift store"
    container = "Name of Container for objects (string)"
    server_url = "Swift store server URL (string)"
    use_file_cache = "When downloading from the server, place downloaded files into the file cache (boolean)"
    download_path = "Path to use for downloaded files if not using the file cache (string)"
    initialise_store = "Whether to create a new, empty, store (boolean)"

    url_lifetime = "How long a temporary URL will last for in seconds (integer)"
    url_lifetime_slack = "Max additional time a URL will be allowed to last in seconds. Use to avoid constant recreation of derived images (integer)"
    url_key = "Private key set for container to authenticate temporary ULRs (string)"
    url_method = "Temporary URL access mechanism (usually GET)"
    
    def __init__(self, config):
        super(SwiftStoreConfig, self).__init__(config)
        self.credentials = CredentialsConfig(None)
        self.container = "test_image_repo"
        self.server_url = "https://swift.rc.nectar.org.au:8888"
        self.use_file_cache = True
        self.download_path = None
        self.initialise_store = False
        
        self._file_cache_path = None
        self._file_cache = None
        
        self.max_size = 0
        self.max_elements = 0

        self.url_lifetime = 3600 * 24 * 2     # 2 days
        self.url_lifetime_slack = 3600 * 24   # 1 day  - To avoid constant thrashing of requests to the object store we give anyhting up to this amount additional life to objects
        self.url_key = "123456789"
        self.url_method = "GET"
        self._assign_config(self, config)

class LocalFileCacheConfig(CacheConfig):
    """Configuration of local file storage.
    """
    cache_path = "Path to directory where local files will cache images"
    initialise = "Whether to create a new clean local file cache"
    
    def __init__(self, config):
        super(LocalFileCacheConfig, self).__init__(config)
        self.cache_path = "/var/tmp/image_server"
        self.initialise = False
        self._assign_config(self, config)


class SwiftCacheConfig(SwiftStoreConfig):
    """Configuration of a Swift store used to hold cached ephemeral objects
    """
    yaml_tag = u'!Swift_Cache_Configuration'
    
    def __init__(self, config):
        super(SwiftCacheConfig, self).__init__(config)
        
class PersistentStoreConfig(BaseConfig):
    """Configuration of the store system used to provide long-term resilient storage of preserved objects
    """    
    yaml_tag = u'!Persistent_Storage_Configuration'
    def __init__(self, config):
        super(PersistentStoreConfig, self).__init__(config)
        self.agent = SwiftStoreConfig(None)
        self._assign_config(self, config)

        
class Configuration(BaseConfig):
    """Top level configuration object
    """
    
    yaml_tag = u'!Main_Image_Repo_Configuration'

    create_new = "Create a new repository with this configuration (boolean)"
    owner = "Identity of the owner of the repository (string)"
    pid_file = "Path of the file in which the PID of a running server will be stored (string)"
    local_file_cache_path = "Path to local filesystem where image files will be cached (string)"
    memory_cache_configuration = "In memory cache for all images"
    local_cache_configuration = "Local file system cache for images, base and derived"
    swift_cache_configuration = "Swift cache of derived images - used to avoid regeneration"
    persisent_store_configuration = "Persistent object store for permanently retained images"
    max_size = "Maximum allocation of space in bytes to store all images, 0 = unlimited (integer)"
    max_images = "Maximum number of any images to store, 0 = unlimited (integer)"
    alarm_threshold = "Threshold of image repository use to signal an alarm at (real in range 0.0:1.0)"
    image_default_format = "Defualt format to deliver images in. (string)"
    
    thumbnail_default_format = "Default image format to generate thumbnails in (string)"
    thumbnail_default_size = "Default size for thumbnails [ int, int ]"
    thumbnail_default_xsize = "Default x-size for thumbnails (integer)"
    thumbnail_default_ysize = "Default y-size for thumbnails (integer)"
    thumbnail_equalise = "Whether to apply histogram equalisation to thumbnails (boolean)"
    thumbnail_liquid_resize = "Whether to allow distortion of the thumbnail aspect ratio for very long or very wide images (boolean)"
    thumbnail_sharpen = "Whether to apply a sharpen operation to thumbnails (boolean)"
    thumbnail_liquid_cutin_ratio = "If applying a distorted resize, what cutin ratio to use for a liquid rescale (real)"
    
    cannonical_format_used = "Whether to convert images to a standard intermediate format (boolean)"
    cannonical_format = "If converting to a cannonical format, what format to use (string)"
    
    def __init__(self, config_file):
        self.create_new = False
        self.owner = None
        self.local_file_cache_path = "/var/tmp/image_repo"
        self.pid_file = "/var/tmp/image_repo_pid"
        self.memory_cache_configuration = CacheConfig(None)    # If we use a slab of memory to cache some images, base and derived
        self.local_cache_configuration = LocalFileCacheConfig(None)    # If we use a local file system to cache some images, base and derived
        self.swift_cache_configuration = SwiftCacheConfig(None)    # If we cache some derived images to avoid regeneration
        self.persistent_store_configuration = SwiftStoreConfig(None)
        self.max_size = 0
        self.max_images = 0
        self.alarm_threshold = 0.8

        self.thumbnail_default_format = "jpg"
        self.thumbnail_default_size = [50,50]
#        self.thumbnail_default_ysize = 50
        self.thumbnail_equalise = True
        self.thumbnail_liquid_resize = True
        self.thumbnail_sharpen = True
        self.thumbnail_liquid_cutin_ratio = 5.0
        
        self.cannonical_format_used = False
        self.cannonical_format = "miff"
        self.image_default_format = 'jpg'
        
        config = None
        if config_file is not None:
            config = self._parse_yaml(config_file)
        self._assign_config(self, config)


class Errors:
    """Program wide error manager.

    Provides a simple class to encapsulate a limit on the number of run-time recoverable errors, to log errors
    as needed, and to manage the translation of internal errors to a form suitable for delivery to the client
    as 4xx errors via the RestFull interface.  Still much to do.
    """
    def __init__(self, limit, exception = RepositoryError):
        self._count = 0
        self._limit = limit
        self._exception = exception
        
    def error(self, kind = None):
        """Keep account of errors that occur, and manage program restart in the face of serious errors. 
        
        :param kind: Optional encapsulation of error
        :type kind:  integer
        :raises: RepositoryError

        """
        if self._limit == -1:
            return
        self._count += 1
        if self._count > self._limit:
            logger.info("Runtime limit of {} errors exceeded".format(self._limit))
            if self._exception is not None:
                raise self._exception
            else:
                raise RepositoryError("Runtime limit of {} errors exceeded".format(self._limit))
            
    def error_count(self):
        return self._count


class SignalHandler:
    """Encapsulates handling of Unix signals for control of the system.

    Class provides the infrastructure to allow for traditional use of Unix signals to control the action
    of the server.

    SIGTERM: force the server to re-read its configuration file and make chages to its operation as approriate
    SIGHUP: force server to shut-down cleanly.
    """

    _logger = None
    
    def __init__(self):
        self._logger = logging.getLogger("image_repository")
        signal.signal(signal.SIGHUP, self.signal_hup_handler)     # Provide for a sighup to restart server
        signal.signal(signal.SIGTERM, self.signal_exit_handler)   # Provide for a kill notification to go into the log file then exit

    @staticmethod
    def signal_exit_handler(signum, frame):
        """Provides a mechanism to log via the logger if the program is terminated via an external signal (a kill -TERM command).
        """
        SignalHandler._logger.info("Exiting with signal {}".format(signum))
        repo.shutdown()
        # Exit
        sys.exit(os.EX_OK)

    @staticmethod
    def signal_hup_handler(signum, frame):
        """Provides a mechanism to field a sighup
        """
        # We should be able to get Werkzeug to restart us                
        SignalHandler._logger.info("SIGTERM received. Reinitialise not supported.")



class ImageRepository:
    """Encapsulates server startup and shutdown

    """
    def __init__(self):
        
        self._logger = None
        self._args = None
        self._config = None
        self._cache_master = None

    def argument_parser(self):
        """Create the argument parser object for command-line instantiation of the Image Repository

        :returns: instance of ArgumentParser
        """
        parser = argparse.ArgumentParser("image_repository", description='Image repository server')
        parser.add_argument('-t', '--trial_run',  action = 'store_true', help = 'Check that as much of the configuration is good as is as possible and exit.')
        parser.add_argument('-T', '--test_run',   action = 'store_true', help = 'Do not link to the persistent store.  Just run with local store')
        parser.add_argument('-v', '--verbose',    action = 'store_true', help = 'Enable informational messages')
        parser.add_argument('-C', '--critical',   action = 'store_true', help = 'Only log CRITICAL messages')
        parser.add_argument('-V', '--debug',      action = 'store_true', help = 'Enable debugging level messages')
        parser.add_argument('-a', '--attached',   action = 'store_true', help = 'Stay attached to the terminal.  Useful debugging.')
        parser.add_argument('-q', '--quiet',      action = 'store_true', help = 'Only log critical messages, turns off warning and error logging - usually means no log output')
        parser.add_argument('-l', '--log_file',                          help = 'Log file. If not specified output goes to standard output')
        parser.add_argument('-c', '--config_log_file',                   help = 'Logging configuration file. Python logger format.')
        parser.add_argument('-i', '--intolerant', action = 'store_true', help = 'Exit on error.')

        control_group = parser.add_mutually_exclusive_group()        
        control_group.add_argument('-R', '--restart',    action = 'store_true', help = 'Restart any existing server process')
        control_group.add_argument('-S', '--stop',       action = 'store_true', help = 'Stop any existing server process')
        control_group.add_argument('-B', '--background', action = 'store_true', help = 'Start a server process in the background')
        
        parser.add_argument('-y', '--yaml_config',                       help = 'Path to YAML format configuration file. Contents override internal defaults on a per element basis.')
        parser.add_argument('-Y', '--dump_yaml',  action = 'store_true', help = 'Dump full program configuration in YAML format to std_out. Useful start for writing a config file.')
        
        return parser

    def build_logger(self, args):
        """Create the logger instance for the Image Repository

        Simple logger configuration that allows logging to nothing, standard output, 
        a file, or allows use of a configuration file for more advanced
        logging destinations. Also captures warnings to the log.

        :param args: parsed arguments from Argument Parser including config values for logger
        :returns: instance of logger.Logger for "image_repository"

        If `args` is `None`, or none of `config_log_file`, `log_file` or `quiet` are defined in `args`,
        a default logger is created that uses a `StreamHandler` to direct log
        messages to standard output.
        
        If `args` is not `None` the following values are used
        
        To control output
        `config_log_file`:
        provides the name of a logger format configuration file to define logging
        `log_file`:
        the path of a file to direct logging output into
        `quiet`:
        avoid directing output to standard output
        
        To control level of logging messages (default level is `WARNING`)
        `critical`: 
        only log `CRITICAL` and above messages
        `verbose`:
        log `INFO` and above messages
        `debug`
        log `DEBUG` and above messages               
        """
        
        if args is not None:
            if args.config_log_file is not None:
                #            handler = logging.FileConfig(args.config_log_file)
                pass
            if args.log_file is not None:
                handler = logging.FileHandler(args.log_file, delay = True)
            else:
                if args.quiet:
                    handler = logging.NullHandler()
                else:
                    handler = logging.StreamHandler()
        else:
            handler = logging.StreamHandler()
        
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        logger = logging.getLogger("image_repository")
        logger.addHandler(handler)
        logging._srcfile = None

        logging_level = logging.WARNING
        if args is not None:
            if args.quiet:
                logging_level = logging.CRITICAL
            elif args.verbose:
                logging_level = logging.INFO
            elif args.debug:
                logging_level = logging.DEBUG
        else:
            logging_level = logging.DEBUG
        
        logger.setLevel(logging_level)    
        logging.captureWarnings(True)
        return logger

    
    def shutdown(self):
        """Manage clean shutdown of the repository"""


        # Ensure that all the persistent entities are safe
        
        try:
            os.remove(self._config.pid_file)
        except OSError:
            self._logger.exception("Failure to remove PID file {}".format(self._config.pid_file))
            sys.exit(os.EX_OSERR)
        sys.exit(os.EX_OK)


    def forced_shutdown(self):
        """Manage a forced shutdown of the repository"""
        
        try:
            os.remove(self._config.pid_file)
        except OSError:
            self._logger.exception("Failure to remove PID file {}".format(self._config.pid_file))
            sys.exit(1)
        sys.exit(os.EX_OK)
        
    def fatal_shutdown(self):
        """Manage shutdown in the face of fatal internal errors"""
        
        try:
            os.remove(self._config.pid_file)
        except OSError:
            pass
#            self._logger.exception("Failure to remove PID file {}".format(self._config.pid_file))
        sys.exit(os.EX_OSERR)

    def cache_master(self):
        return self._cache_master

    
    # This is wrong
    def run(self, app, debug = False):
        global args, logger, error, config
        try:
            app.run(debug = debug)
            self.shutdown()
        except KeyboardInterrupt:
            self._logger.info("Keyboard interrupt halts processing.")
            self.shutdown()
        except RepositoryError:
            self.fatal_shutdown()
            #    except Exception as ex:
            #        logger.exception("Unhandled exception, exiting.", exc_info = ex)
            #        sys.exit(1)
        else:
            exit(os.EX_OSERR)
        sys.exit(os.EX_OK)

    def repository_start(self):
        # lazy load of image database
        self._cache_master = Caches.startup(config)
        
    def repository_server(self):
        """Top level instantiation of the Image Repository
        
        This is the function that is called to start up the repository.
        It is responsible for argument parsing, configuration, creation of all the
        entities that comprise the server, and initiating the server's normal running.
        
        It will also field exit of the server, for both normal and abnormal exit conditions.    
        """
    
        global args, logger, error, config, repo

        try:
            parser = self.argument_parser()
            args = parser.parse_args()
            self._logger = self.build_logger(args)
            logger = self._logger
            repo = self # Yuk
            
            config = Configuration(args.yaml_config)
            self._config = config  # TODO - fix these references
            if args.dump_yaml:
                print config

            if args.background:
                # We are going to run the server as a sub-process
                # fork it
                try:
                    server_pid = os.fork()
                except OSError:
                    self._logger.exception("Fork of server process failed")
                    exit(os.EX_OSERR)
                if server_pid != 0:
                    self._logger.info("Child process is {}".format(server_pid))
                    exit(os.EX_OK)
                
            ImageNames.ImageName.set_configuration(config)
            ImageType.ImageHandle.set_configuration(config)
            ImageType.ImageInstance.set_configuration(config)
            
            error = Errors(0 if args.intolerant else 20, RepositoryError)
            signals = SignalHandler()
    
            if args.trial_run:
                self._logger.info("Trial run. Only checking configuration")
                exit(os.EX_OK)

            if args.restart or args.stop:
                # Find the running server and signal it to restart or stop
                try:
                    with open(config.pid_file, 'r') as the_file:
                        server_pid = int(the_file.read())
                except IOError:
                    self._logger.exception("Failure to read server PID from {}. Server may not be running".format(config.pid_file))
                    exit(os.EX_OSFILE)
                try:
                    if args.restart:
                        # We should be able to use the Werkzeug reloader, but there doesn't seem to be any easy interface
                        # OTOH, the reloader should obviate any need to use a SIGHUP when the config changes.
                        os.kill(server_pid, signal.SIGHUP)
                    if args.stop:
                        os.kill(server_pid, signal.SIGTERM)
                except:
                    self._logger.exception("Failure in sending signal to server process {}. Server may not be running".format(server_pid))
                    exit(os.EX_OSERR)
                exit(os.EX_OK)
                                                           
            if not args.test_run:
                self._logger.info("Image repository server starts.")
                self._logger.info("PID: {}".format(os.getpid()))
                try:
                    with open(config.pid_file, 'w') as the_file:
                        the_file.write(str(os.getpid()))
                except IOError:
                    self._logger.exception("Failure to write PID to {}".format(config.pid_file))                  
            else:
                self._logger.info("Image repository server starts in cache self test mode.")
                self._logger.info("PID: {}".format(os.getpid()))
                # We can add any useful self test code here.
                Caches.stress_test(config)
                exit(os.EX_OK)

            return

        except KeyboardInterrupt:
            self._logger.info("Keyboard interrupt halts processing.")
            self.forced_shutdown()
        except RepositoryError:
            self.fatal_shutdown()
        except Exception as ex:
            logger.exception("Unhandled exception, exiting.", exc_info = ex)
            sys.exit(os.EX_OSERR)
        sys.exit(os.EX_OK)

def main():
    repo = ImageRepository()
    repo.repository_server()
    
if __name__ == "__main__":
    main()
