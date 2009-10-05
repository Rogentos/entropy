# -*- coding: utf-8 -*-
"""

    @author: Fabio Erculiani <lxnay@sabayonlinux.org>
    @contact: lxnay@sabayonlinux.org
    @copyright: Fabio Erculiani
    @license: GPL-2

    B{Entropy Framework core module}.

    This module contains base classes used by entropy.client,
    entropy.server and entropy.services.

    "Singleton" is a class that is inherited from singleton objects.

"""
import sys
import os
import inspect
from entropy.const import etpConst

class Singleton(object):

    """
    If your class wants to become a sexy Singleton,
    subclass this and replace __init__ with init_singleton.
    Your subclass can expose a method called "is_destroyed()" that
    returns a bool stating if singleton instance has been destroyed.
    """

    def __new__(cls, *args, **kwds):

        singleton = getattr(cls, '__singleton__', None)
        if singleton is not None:
            destroyed = getattr(singleton, 'is_destroyed', None)
            if destroyed is not None:
                if not destroyed():
                    return singleton
                cls.__singleton__ = None
            else:
                return singleton

        singleton = object.__new__(cls)
        singleton.init_singleton(*args, **kwds)
        cls.__singleton__ = singleton
        return singleton

    def __init__(self, *args, **kwargs):
        """
        This is a fake method, necessary for Python 3.
        """
        pass

class EntropyPluginFactory:

    """
    Generic Entropy Components Plugin Factory (loader).
    """

    _PLUGIN_SUFFIX = "_plugin"
    _PYTHON_EXTENSION = ".py"

    def __init__(self, base_plugin_class, plugin_package_module,
        default_plugin_name = None, fallback_plugin_name = None,
        egg_entry_point_group = None):
        """
        Entropy Generic Plugin Factory constructor.
        MANDATORY: every plugin module/package(name) must end with _plugin
        suffix.

        Base plugin classes must have the following class attributes set:

            - BASE_PLUGIN_API_VERSION: integer describing API revision in use
              in class

        Subclasses of Base plugin class must have the following class
        attributes set:

            - PLUGIN_API_VERSION: integer describing the currently implemented
              plugin API revision, must match with BASE_PLUGIN_API_VERSION
              above otherwise plugin won't be loaded and a warning will be
              printed.

        Moreover, plugin classes must be "Python new-style classes", otherwise
        parser won't be able to determine if classes have subclasses and thus
        pick the proper object (one with no subclasses!!).
        See: http://www.python.org/doc/newstyle -- in other words, you have
        to inherit the built-in "object" class (yeah, it's called object).
        So, even if using normal classes could work, if you start doing nasty
        things (nested inherittance of plugin classes), behaviour cannot
        be guaranteed.
        If it's not clear, let me repeat once again, valid plugin classes
        must not have subclasses around! Think about it, it's an obvious thing.

        If plugin class features a "PLUGIN_DISABLED" class attribute with
        a boolean value of True, such plugin will be ignored.

        If egg_entry_point_group is specified, Python Egg support is enabled
        and classes are loaded via this infrastructure.
        NOTE: if egg_entry_point_group is set, you NEED the setuptools package.

        @param base_plugin_class: Base EntropyPlugin-based class that valid
            plugin classes must inherit from.
        @type base_plugin_class: class
        @param plugin_package_module: every plugin repository must work as
            Python package, the value of this argument must be a valid
            Python package module that can be scanned looking for valid
            Entropy Plugin classes.
        @type plugin_package_module: Python module
        @keyword default_plugin_name: identifier of the default plugin to load
        @type default_plugin_name: string
        @keyword fallback_plugin_name: identifier of the fallback plugin to load
            if default is not available
        @type fallback_plugin_name: string
        @keyword egg_entry_point_group: valid Python Egg entry point group, in
            this case, Python Egg support is used
        @type egg_entry_point_group: string
        @raise AttributeError: when passed plugin_package_module is not a
            valid Python package module
        """
        self.__modfile = plugin_package_module.__file__
        self.__base_class = base_plugin_class
        self.__plugin_package_module = plugin_package_module
        self.__default_plugin_name = default_plugin_name
        self.__fallback_plugin_name = fallback_plugin_name
        self.__egg_entry_group = egg_entry_point_group
        self.__cache = None

    def clear_cache(self):
        """
        Clear available plugins cache. When calling get_available_plugins()
        module object is parsed again.
        """
        self.__cache = None

    def _inspect_object(self, obj):
        """
        This method verifies if given object is a valid plugin.

        @return: True, if valid
        @rtype: bool
        """

        base_api = self.__base_class.BASE_PLUGIN_API_VERSION

        if not inspect.isclass(obj):
            return False

        if not issubclass(obj, self.__base_class):
            return False

        if hasattr(obj, '__subclasses__'):
            # new style class
            if obj.__subclasses__(): # only lower classes taken
                return False
        else:
            sys.stderr.write("!!! Entropy Plugin warning: " \
                "%s is not a new style class !!!\n" % (obj,))

        if obj is self.__base_class:
            # in this case, obj is our base class,
            # so we are very sure that obj is not valid
            return False

        if not hasattr(obj, "PLUGIN_API_VERSION"):
            sys.stderr.write("!!! Entropy Plugin warning: " \
                "no PLUGIN_API_VERSION in %s !!!\n" % (obj,))
            return False

        if obj.PLUGIN_API_VERSION != base_api:
            sys.stderr.write("!!! Entropy Plugin warning: " \
                "PLUGIN_API_VERSION mismatch in %s !!!\n" % (obj,))
            return False

        if hasattr(obj, 'PLUGIN_DISABLED'):
            if obj.PLUGIN_DISABLED:
                # this plugin has been disabled
                return False

        return True

    def _scan_dir(self):
        """
        Scan modules in given directory looking for a valid plugin class.
        Directory is os.path.dirname(self.__modfile).

        @return: module dictionary composed by module name as key and plugin
            class as value
        @rtype: dict
        """
        available = {}
        pkg_modname = self.__plugin_package_module.__name__
        mod_dir = os.path.dirname(self.__modfile)

        for modname in os.listdir(mod_dir):

            if modname.startswith("__"):
                continue # python stuff
            if not (modname.endswith(EntropyPluginFactory._PYTHON_EXTENSION) \
                or "." not in modname):
                continue # not something we want to load

            if modname.endswith(EntropyPluginFactory._PYTHON_EXTENSION):
                modname = modname[:-len(EntropyPluginFactory._PYTHON_EXTENSION)]

            if not modname.endswith(EntropyPluginFactory._PLUGIN_SUFFIX):
                continue

            # remove suffix
            modname_clean = modname[:-len(EntropyPluginFactory._PLUGIN_SUFFIX)]

            modpath = "%s.%s" % (pkg_modname, modname,)

            try:
                __import__(modpath)
            except ImportError as err:
                sys.stderr.write("!!! Entropy Plugin warning, cannot " \
                    "load module: %s | %s !!!\n" % (modpath, err,))
                continue

            for obj in list(sys.modules[modpath].__dict__.values()):

                valid = self._inspect_object(obj)
                if not valid:
                    continue

                available[modname_clean] = obj

        return available

    def _scan_egg_group(self):
        """
        Scan classes in given Python Egg group name looking for a valid plugin.

        @return: module dictionary composed by module name as key and plugin
            class as value
        @rtype: dict
        """
        # needs setuptools
        import pkg_resources
        available = {}

        for entry in pkg_resources.iter_entry_points(self.__egg_entry_group):

            obj = entry.load()
            valid = self._inspect_object(obj)
            if not valid:
                continue
            available[entry.name] = obj

        return available


    def get_available_plugins(self):
        """
        Return currently available EntropyPlugin plugin classes.
        Note: Entropy plugins can either be Python packages or modules and
        their name MUST end with PluginFactory._PLUGIN_SUFFIX ("_plugin").

        @return: dictionary composed by Entropy plugin id as key and Entropy
            Python module as value
        @rtype: dict
        """
        if self.__cache is not None:
            return self.__cache.copy()

        if self.__egg_entry_group:
            available = self._scan_egg_group()
        else:
            available = self._scan_dir()

        self.__cache = available.copy()
        return available

    def get_default_plugin(self):
        """
        Return currently configured Entropy Plugin class.

        @return: Entropy plugin class
        @rtype: entropy.core.EntropyPlugin
        @raise KeyError: if default plugin is not set or not found
        """
        available = self.get_available_plugins()
        plugin = self.__default_plugin_name
        fallback = self.__fallback_plugin_name
        klass = available.get(plugin)

        if klass is None:
            import warnings
            warnings.warn("%s: %s" % (
                "selected Plugin not available, using fallback", plugin,))
            klass = available.get(fallback)

        if klass is None:
            raise KeyError

        return klass
