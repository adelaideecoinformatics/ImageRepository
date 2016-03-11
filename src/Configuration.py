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
        from yaml import dump as dump
        return string.join(dump(self, indent = 4, default_flow_style = False, width = 1200).split("\\n"), "\n")
                    

    @classmethod
    def to_yaml(cls, dumper, data):
        """Dump a yaml representation of the configuration object and its current values.
        """
        return yaml.SequenceNode(tag=u'tag:yaml.org,2002:seq', value=[
            yaml.ScalarNode(tag = 'tag:yaml.org,2002:str', value = u"{} : {}".format(entry, str(data.__dict__[entry]))) if entry[:1] != "_" else None for entry in data.__dict__.iterkeys()
        ])



        return yaml.MappingNode(tag=u'tag:yaml.org,2002:seq', value=[
            (yaml.ScalarNode(tag = 'tag:yaml.org,2002:str', value = entry), yaml.ScalarNode(tag= 'tag:yaml.org,2002:str',
                                                                                            value = str(data.__dict__[entry]) + "  # " + str(data.__dict__[entry])))
            if entry[:1] != "_" else None for entry in data.__dict__.iterkeys()
        ])

    
class CacheConfig(BaseConfig):
    """Cache operation configuration
    """

    
    yaml_tag = u'!Cache_Configuration'
    evict_free_threshold = "Percentage of store allocation used to begin eviction"
    evict_hysterysis = "Percentage of store allocation used less than evict threshold to allow ending eviction"
    priority = "Which object to favour for retention: one of newest, largest, smallest, thumbnail"
    writeback = "Writeback strategy one of eager, lazy, never"
    alarm_free_threshold = "Proportion of store allocation free to signal alarm"
    max_size = "Maximum size of store (in GB), 0 = unlimited"
    max_elements = "Maximum number of elements to store. 0 = unlimited"
    
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
    username = ""
    authurl = ""
    tennant = ""
    password = ""

    def __init__(self, config):
        super(CredentialsConfig, self).__init__(config)
        self.username = ("env", "OS_USERNAME")
        self.tenant = ("env", "OS_TENANT_NAME")
        self.tenant_id = ("env", "OS_TENANT_ID")
        self.authurl = ("env", "OS_AUTH_URL")
        self.password = ("env", "OS_PASSWORD")
        
        self._assign_config(self, config)
        
        self.the_password = self._find_param(self.password)
        self.the_username = self._find_param(self.username)
        self.the_authurl = self._find_param(self.authurl)
        self.the_tenant_name = self._find_param(self.tenant)
        self.the_tenant_id = self._find_param(self.tenant_id)

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
    credentials = "Credentials needed to access Swift store: CredentialsConfig"
    container = "Name of Container for objects: string"
    server = "Swift store server URL: string"
    use_file_cache = "When downloading from the server, place downloaded files into the file cache: Boolean"
    download_path = "Path to use for downloaded files if not using the file cache: string"
    
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
        self.url_prefix = "/v1"
        
        self._assign_config(self, config)

class LocalFileCacheConfig(CacheConfig):
    """Configuration of local file storage.
    """
    
    def __init__(self, config):
        super(LocalFileCacheConfig, self).__init__(config)
        self.cache_path = "/var/tmp/image_server"
        self.initialise = False
        self._assign_config(self, config)


class SwiftCacheConfig(CacheConfig):
    """Configuration of a Swift store used to hold cached ephemeral objects
    """
    
    def __init__(self, config):
        super(SwiftCacheConfig, self).__init__(config)
        self.container = "test_image_repo_cache"
        self.credentials = CredentialsConfig(None)
        self.server_url = "https://swift.rc.nectar.org.au:8888"
        self.use_file_cache = True
        self.download_path = None
        self.initialise_store = False
                
        self._file_cache_path = None
        self._file_cache = None        
        
        self._assign_config(self, config)

        self.url_lifetime = 3600 * 24 * 2
        self.url_lifetime_slack = 3600 * 24  
        self.url_key = "123456789"
        self.url_method = "GET"
        self.url_prefix = "/v1"
        
        
class PersistentStoreConfig(BaseConfig):
    """Configuration of the store system used to provide long-term resilient storage of preserved objects
    """
    
    yaml_tag = u'!Persistent_Storage_Configuration'
    def __init__(self, config):
        super(PersistentStoreConfig, self).__init__(config)
        self.agent = SwiftStoreConfig(None)
        self._assign_config(self, config)

        
class WalEConfig(BaseConfig):
    """Configuration of the Well-E SQL database snapshot mechanism
    """
    
    yaml_tag = u'!Wall-E_configuration'
    use_image_repo = "Use the image repository to hold database snapshots"
    pool_size = "Pool size"
    gpg_key_id = "If set, encryption with this key will be used for the database snapshots"
    
    def __init__(self, config):
        self.use_image_repo = True
        self.pool_size = 8
        self.gpg_key_id = None
        self._assign_config(self, config)

        
class Configuration(BaseConfig):
    """Top level configuration object
    """
    
    yaml_tag = u'!Main_Image_Repo_Configuration'

    create_new = "Create a new repository with this configuration"
    owner = "Identity of the owner of the repository"
    db_versions_to_keep = "Number of recoverable versions of the description database to preserve"
    local_file_cache_path = "Path to local filesystem where image files will be cached"
    local_cache_configuration = "If we use a local file system to cache some images, base and derived"
    swift_cache_configuration = "If we cache some derived images to avoid regeneration"
    persisent_store = "Config of persistent object store for images"
    database_persistence = "Configure mechanism for database persistence"
    max_size = "Maximum allocation of image store"
    max_images = "Maximum number of images to store"
    alarm_threshold = "Threshold to alarm image repository use"
    
    def __init__(self, config_file):
        self.create_new = False
        self.owner = None
        self.db_versions_to_keep = 3
        self.local_file_cache_path = "/var/tmp/image_repo"
        self.memory_cache_configuration = CacheConfig(None)    # If we use a slab of memory to cache some images, base and derived
        self.local_cache_configuration = LocalFileCacheConfig(None)    # If we use a local file system to cache some images, base and derived
        self.swift_cache_configuration = SwiftCacheConfig(None)    # If we cache some derived images to avoid regeneration
        self.persistent_store_configuration = SwiftStoreConfig(None)
        self.max_size = 0
        self.max_images = 0
        self.alarm_threshold = 0.8

        self.thumbnail_default_format = "jpg"
        self.thumbnail_default_size = (50,50)
        self.thumbnail_equalise = True
        self.thumbnail_liquid_resize = True
        self.thumbnail_sharpen = True
        self.thumbnail_liquid_cutin_ratio = 5.0

 
        
        self.use_cannonical_format = False
        self.cannonical_format = "miff"
        
        config = None
        if config_file is not None:
            config = self._parse_yaml(config_file)
        self._assign_config(self, config)



        




# TODO - move the exceptions into this class and consolidate management

class Errors:
    """Program wide error manager.

    Provides a simple class to encapsulate a limit on the number of run-time recoverable errors, to log errors
    as needed, and to manage the translation of internal errors to a form suitable for delivery to the client
    as 4xx errors via the RestFull interface.
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
        signal.signal(signal.SIGHUP, self.signal_exit_handler)    # Provide for a kill notification to go into the log file
        signal.signal(signal.SIGTERM, self.signal_term_handler)   # Provide for a sigterm to restart server

    @staticmethod
    def signal_exit_handler(signum, frame):
        """Provides a mechanism to log via the logger if the program is terminated via an external signal (ie a kill command).
        """
        SignalHandler._logger.info("Exiting with signal {}".format(signum))
        # Shutdown()
        # Exit
        sys.exit(0)

    @staticmethod
    def signal_term_handler(signum, frame):
        """Provides a mechanism to field a sigterm
        """
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
        parser.add_argument('-l', '--log_file',                         help = 'Log file. If not specified output goes to standard output')
        parser.add_argument('-c', '--config_log_file',                  help = 'Logging configuration file. Python logger format.')
        parser.add_argument('-i', '--intolerant',  action = 'store_true',  help = 'Exit on error.')

        parser.add_argument('-y', '--yaml_config',        help = 'Path to YAML format configuration file. Contents override internal defaults on a per element basis.')
        parser.add_argument('-Y', '--dump_yaml',    action = 'store_true', help = 'Dump full program configuration in YAML format to std_out. Useful start for writing a config file.')
    
    
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

        #    logging_level = logging.WARNING
        logging_level = logging.DEBUG
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
        """Manage clean shutdown of the repository
        
        """
        sys.exit(0)

        
    def fatal_shutdown(self):
        """Manage shutdown in the face of fatal internal errors
        
        """
        sys.exit(1)

    def cache_master(self):
        return self._cache_master


    def run(self, app, debug = False):
        global args, logger, error, config
        try:
            app.run(debug = debug)
            self.shutdown()
        except KeyboardInterrupt:
            self._logger.info("Keyboard interrupt halts processing.")
            sys.exit(0)
        except RepositoryError:
            sys.exit(1)
            #    except Exception as ex:
            #        logger.exception("Unhandled exception, exiting.", exc_info = ex)
            #        sys.exit(1)
        
            sys.exit(0)
            
    def repository_server(self):
        """Top level instantiation of the Image Repository
        
        This is the function that is called to start up the repository.
        It is responsible for argument parsing, configuration, creation of all the
        entities that comprise the server, and initiating the server's normal running.
        
        It will also field exit of the server, for both normal and abnormal exit conditions.    
        """
    
        global args, logger, error, config

        try:
            parser = self.argument_parser()
            args = parser.parse_args()
            self._logger = self.build_logger(args)
            
            
            config = Configuration(args.yaml_config)
            if args.dump_yaml:
                print config

            ImageNames.ImageName.set_configuration(config)
            ImageType.ImageHandle.set_configuration(config)
            ImageType.ImageInstance.set_configuration(config)

            
            error = Errors(0 if args.intolerant else 20, RepositoryError)
            signals = SignalHandler()
    
            if args.trial_run:
                self._logger.info("Trial run. Checking configuration")
                exit(0)

            if not args.test_run:
                # connect to server
                # load database
                # start running server
                self._logger.info("Image repository server starts.")
                self._logger.info("PID: {}".format(os.getpid()))
                self._cache_master = Caches.startup(config)
            else:
                # Look for existing local database
                # Look for existing local store
                # Create either if not present
                # Run server in test mode
                self._logger.info("Image repository server starts in test mode.")
                self._logger.info("PID: {}".format(os.getpid()))

                Caches.stress_test(config)

            return
            
            """
            store_name = config.persistent_store.server
            credentials = config.persistent_store.credentials
            
            swift = Stores.SwiftImageStore( store_name, credentials)
            
            print swift
            print swift.stats()
            """

        
            # self.shutdown()

        
        except KeyboardInterrupt:
            self._logger.info("Keyboard interrupt halts processing.")
            sys.exit(0)
        except RepositoryError:
            sys.exit(1)
            #    except Exception as ex:
            #        logger.exception("Unhandled exception, exiting.", exc_info = ex)
            #        sys.exit(1)
        
            sys.exit(0)

if __name__ == "__main__":
    repo = ImageRepository()
    repo.repository_server()
