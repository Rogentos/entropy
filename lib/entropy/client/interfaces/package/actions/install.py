# -*- coding: utf-8 -*-
"""

    @author: Fabio Erculiani <lxnay@sabayon.org>
    @contact: lxnay@sabayon.org
    @copyright: Fabio Erculiani
    @license: GPL-2

    B{Entropy Package Manager Client Package Interface}.

"""
import errno
import os
import shutil
import stat
import time

from entropy.const import etpConst, const_convert_to_unicode, \
    const_convert_to_rawstring, const_is_python3
from entropy.exceptions import EntropyException
from entropy.i18n import _
from entropy.output import darkred, red, purple, brown, blue, darkgreen, teal

import entropy.dep
import entropy.tools

from ._manage import _PackageInstallRemoveAction

from .. import _content as Content
from .. import preservedlibs


class _PackageInstallAction(_PackageInstallRemoveAction):
    """
    PackageAction used for package installation.
    """

    class InvalidArchitecture(EntropyException):
        """
        Raised when a package for another architecture is attempted
        to be installed.
        """

    NAME = "install"

    def __init__(self, entropy_client, package_match, opts = None):
        """
        Object constructor.
        """
        super(_PackageInstallAction, self).__init__(
            entropy_client, package_match, opts = opts)

    def finalize(self):
        """
        Finalize the object, release all its resources.
        """
        super(_PackageInstallAction, self).finalize()
        if self._meta is not None:
            meta = self._meta
            self._meta = None
            meta.clear()

    def setup(self):
        """
        Setup the PackageAction.
        """
        if self._meta is not None:
            # already configured
            return

        metadata = {}
        splitdebug_metadata = self._get_splitdebug_metadata()
        metadata.update(splitdebug_metadata)

        inst_repo = self._entropy.installed_repository()
        repo = self._entropy.open_repository(self._repository_id)

        misc_settings = self._entropy.ClientSettings()['misc']
        metadata['edelta_support'] = misc_settings['edelta_support']
        is_package_repo = self._repository_id.endswith(
            etpConst['packagesext'])

        # if splitdebug is enabled, check if it's also enabled
        # via package.splitdebug
        if metadata['splitdebug']:
            # yeah, this has to affect exported splitdebug setting
            # because it is read during package files installation
            # Older splitdebug data was in the same package file of
            # the actual content. Later on, splitdebug data was moved
            # to its own package file that gets downloaded and unpacked
            # only if required (if splitdebug is enabled)
            metadata['splitdebug'] = self._package_splitdebug_enabled(
                self._package_match)

        # fetch abort function
        metadata['fetch_abort_function'] = self._opts.get(
            'fetch_abort_function')

        # Used by Spm.entropy_install_unpack_hook()
        metadata['repository_id'] = self._repository_id
        metadata['package_id'] = self._package_id

        install_source = etpConst['install_sources']['unknown']
        meta_inst_source = self._opts.get('install_source', install_source)
        if meta_inst_source in list(etpConst['install_sources'].values()):
            install_source = meta_inst_source
        metadata['install_source'] = install_source

        metadata['already_protected_config_files'] = {}
        metadata['configprotect_data'] = []
        metadata['triggers'] = {}
        metadata['atom'] = repo.retrieveAtom(self._package_id)
        metadata['slot'] = repo.retrieveSlot(self._package_id)

        ver, tag, rev = repo.getVersioningData(self._package_id)
        metadata['version'] = ver
        metadata['versiontag'] = tag
        metadata['revision'] = rev

        metadata['extra_download'] = []
        metadata['splitdebug_pkgfile'] = True
        if not is_package_repo:
            metadata['splitdebug_pkgfile'] = False
            extra_download = repo.retrieveExtraDownload(self._package_id)
            if not metadata['splitdebug']:
                extra_download = [x for x in extra_download if \
                    x['type'] != "debug"]
            metadata['extra_download'] += extra_download

        metadata['category'] = repo.retrieveCategory(self._package_id)
        metadata['download'] = repo.retrieveDownloadURL(self._package_id)
        metadata['name'] = repo.retrieveName(self._package_id)
        metadata['checksum'] = repo.retrieveDigest(self._package_id)
        sha1, sha256, sha512, gpg = repo.retrieveSignatures(self._package_id)
        signatures = {
            'sha1': sha1,
            'sha256': sha256,
            'sha512': sha512,
            'gpg': gpg,
        }
        metadata['signatures'] = signatures
        metadata['conflicts'] = self._get_package_conflicts(
            repo, self._package_id)

        description = repo.retrieveDescription(self._package_id)
        if description:
            if len(description) > 74:
                description = description[:74].strip()
                description += "..."
        metadata['description'] = description

        # this is set by __install_package() and required by spm_install
        # phase
        metadata['installed_package_id'] = None
        metadata['remove_package_id'] = -1

        metadata['remove_metaopts'] = {
            'removeconfig': True,
        }
        metadata['remove_metaopts'].update(
            self._opts.get('remove_metaopts', {}))

        metadata['merge_from'] = None
        mf = self._opts.get('merge_from')
        if mf is not None:
            metadata['merge_from'] = const_convert_to_unicode(mf)
        metadata['removeconfig'] = self._opts.get('removeconfig', False)

        remove_package_id, _inst_rc = inst_repo.atomMatch(
            entropy.dep.dep_getkey(metadata['atom']),
            matchSlot = metadata['slot'])
        metadata['remove_package_id'] = remove_package_id

        # setup the list of provided libraries that we're going to remove
        if metadata['remove_package_id'] != -1:
            repo_libs = repo.retrieveProvidedLibraries(self._package_id)
            inst_libs = inst_repo.retrieveProvidedLibraries(
                metadata['remove_package_id'])
            metadata['removed_libs'] = frozenset(inst_libs - repo_libs)
        else:
            metadata['removed_libs'] = frozenset()

        # collects directories whose content has been modified
        # this information is then handed to the Trigger
        metadata['affected_directories'] = set()
        metadata['affected_infofiles'] = set()

        # smartpackage ?
        metadata['smartpackage'] = False
        # set unpack dir and image dir
        if is_package_repo:

            try:
                compiled_arch = repo.getSetting("arch")
                arch_fine = compiled_arch == etpConst['currentarch']
            except KeyError:
                arch_fine = True # sorry, old db, cannot check

            if not arch_fine:
                raise self.InvalidArchitecture(
                    "Package compiled for a different architecture")

            repo_data = self._settings['repositories']
            repo_meta = repo_data['available'][self._repository_id]
            metadata['smartpackage'] = repo_meta['smartpackage']
            metadata['pkgpath'] = repo_meta['pkgpath']

        else:
            metadata['pkgpath'] = self.get_standard_fetch_disk_path(
                metadata['download'])

        metadata['unpackdir'] = etpConst['entropyunpackdir'] + \
            os.path.sep + self._escape_path(metadata['download'])

        metadata['imagedir'] = metadata['unpackdir'] + os.path.sep + \
            etpConst['entropyimagerelativepath']

        metadata['pkgdbpath'] = os.path.join(metadata['unpackdir'],
            "edb/pkg.db")

        if metadata['remove_package_id'] == -1:
            # nothing to remove, fresh install
            metadata['removecontent_file'] = None
        else:
            metadata['removeatom'] = inst_repo.retrieveAtom(
                metadata['remove_package_id'])

            # generate content file
            content = inst_repo.retrieveContentIter(
                metadata['remove_package_id'],
                order_by="file", reverse=True)
            metadata['removecontent_file'] = \
                self._generate_content_file(content)

            remove_trigger = inst_repo.getTriggerData(
                metadata['remove_package_id'])
            metadata['triggers']['remove'] = remove_trigger

            remove_trigger['affected_directories'] = \
                metadata['affected_directories']
            remove_trigger['affected_infofiles'] = \
                metadata['affected_infofiles']

            remove_trigger['spm_repository'] = inst_repo.retrieveSpmRepository(
                metadata['remove_package_id'])
            remove_trigger.update(splitdebug_metadata)

            remove_trigger['accept_license'] = self._get_licenses(
                inst_repo, metadata['remove_package_id'])

            # setup config_protect and config_protect_mask metadata before it's
            # too late.
            protect = self._get_config_protect_metadata(
                inst_repo, metadata['remove_package_id'],
                _metadata = metadata)
            metadata.update(protect)

        metadata['phases'] = []
        if metadata['conflicts']:
            metadata['phases'].append(self._remove_conflicts)

        if metadata['merge_from']:
            metadata['phases'].append(self._merge)
        else:
            metadata['phases'].append(self._unpack)

        # preinstall placed before preremove in order
        # to respect Spm order
        metadata['phases'].append(self._setup)
        metadata['phases'].append(self._pre_install)

        metadata['phases'].append(self._install)
        if metadata['remove_package_id'] != -1:
            metadata['phases'].append(self._pre_remove)
            metadata['phases'].append(self._install_clean)
        else:
            metadata['phases'].append(self._preserved_libs_gc)

        if metadata['remove_package_id'] != -1:
            metadata['phases'].append(self._post_remove)
            metadata['phases'].append(self._post_remove_install)

        metadata['phases'].append(self._install_spm)
        metadata['phases'].append(self._post_install)
        metadata['phases'].append(self._cleanup)

        install_trigger = repo.getTriggerData(self._package_id)
        metadata['triggers']['install'] = install_trigger

        install_trigger['unpackdir'] = metadata['unpackdir']
        install_trigger['imagedir'] = metadata['imagedir']
        install_trigger['spm_repository'] = repo.retrieveSpmRepository(
            self._package_id)

        metadata['accept_license'] = self._get_licenses(
            repo, self._package_id)
        install_trigger['accept_license'] = metadata['accept_license']

        install_trigger.update(splitdebug_metadata)

        self._meta = metadata

    def _run(self):
        """
        Execute the action. Return an exit status.
        """
        self.setup()

        spm_class = self._entropy.Spm_class()
        exit_st = spm_class.entropy_install_setup_hook(
            self._entropy, self._meta)
        if exit_st != 0:
            return exit_st

        for method in self._meta['phases']:
            exit_st = method()
            if exit_st != 0:
                break
        return exit_st

    def _escape_path(self, path):
        """
        Some applications (like ld) don't like ":" in path, others just don't
        escape paths at all. So, it's better to avoid to use field separators
        in path.
        """
        path = path.replace(":", "_")
        path = path.replace("~", "_")
        return path

    def _get_package_conflicts(self, entropy_repository, package_id):
        """
        Return a set of conflict dependencies for the given package.
        """
        conflicts = entropy_repository.retrieveConflicts(package_id)
        inst_repo = self._entropy.installed_repository()

        found_conflicts = set()
        for conflict in conflicts:
            inst_package_id, _inst_rc = inst_repo.atomMatch(conflict)
            if inst_package_id == -1:
                continue

            # check if the package shares the same key and slot
            match_data = entropy_repository.retrieveKeySlot(package_id)
            installed_match_data = inst_repo.retrieveKeySlot(inst_package_id)
            if match_data != installed_match_data:
                found_conflicts.add(inst_package_id)

        # auto conflicts support
        found_conflicts |= self._entropy._generate_dependency_inverse_conflicts(
            (package_id, entropy_repository.name), just_id=True)

        return found_conflicts

    def _remove_conflicts(self):
        """
        Execute the package conflicts removal phase.
        """
        inst_repo = self._entropy.installed_repository()
        confl_package_ids = [x for x in self._meta['conflicts'] if \
            inst_repo.isPackageIdAvailable(x)]
        if not confl_package_ids:
            return 0

        # calculate removal dependencies
        # system_packages must be False because we should not exclude
        # them from the dependency tree in any case. Also, we cannot trigger
        # DependenciesNotRemovable() exception, too.
        proposed_pkg_ids = self._entropy.get_removal_queue(confl_package_ids,
            system_packages = False)
        # we don't want to remove the whole inverse dependencies of course,
        # but just the conflicting ones, in a proper order
        package_ids = [x for x in proposed_pkg_ids if x in confl_package_ids]
        # make sure that every package is listed in package_ids before
        # proceeding, cannot keep packages behind anyway, and must be fault
        # tolerant. Besides, having missing packages here should never happen.
        package_ids += [x for x in confl_package_ids if x not in \
            package_ids]

        if not package_ids:
            return 0

        factory = self._entropy.PackageActionFactory()

        for package_id in package_ids:

            pkg = factory.get(
                factory.REMOVE_ACTION,
                (package_id, inst_repo.name),
                opts = self._meta['remove_metaopts'])
            pkg.set_xterm_header(self._xterm_header)

            exit_st = pkg.start()
            pkg.finalize()
            if exit_st != 0:
                return exit_st

        return 0

    def _unpack_package(self, download, package_path, image_dir, pkg_dbpath):
        """
        Effectively unpack the package tarballs.
        """
        txt = "%s: %s" % (
            blue(_("Unpacking")),
            red(os.path.basename(download)),
        )
        self._entropy.output(
            txt,
            importance = 1,
            level = "info",
            header = red("   ## ")
        )

        self._entropy.logger.log(
            "[Package]",
            etpConst['logging']['normal_loglevel_id'],
            "Unpacking package: %s" % (download,)
        )

        # removed in the meantime? fail.
        # this is just a safety measure, but won't do anything
        # against races.
        if not os.path.isfile(package_path):
            self._entropy.logger.log(
                "[Package]",
                etpConst['logging']['normal_loglevel_id'],
                "Error, package was removed: %s" % (package_path,)
            )
            return 1

        # make sure image_dir always exists
        # pkgs not providing any file would cause image_dir
        # to not be created by uncompress_tarball
        try:
            os.makedirs(image_dir, 0o755)
        except OSError as err:
            if err.errno != errno.EEXIST:
                self._entropy.logger.log(
                    "[Package]", etpConst['logging']['normal_loglevel_id'],
                    "Unable to mkdir: %s, error: %s" % (
                        image_dir, repr(err),)
                )
                self._entropy.output(
                    "%s: %s" % (brown(_("Unpack error")), err.errno,),
                    importance = 1,
                    level = "error",
                    header = red("   ## ")
                )
                return 1

        # pkg_dbpath is only non-None for the base package file
        # extra package files don't carry any other edb information
        if pkg_dbpath is not None:
            # extract entropy database from package file
            # in order to avoid having to read content data
            # from the repository database, which, in future
            # is allowed to not provide such info.
            pkg_dbdir = os.path.dirname(pkg_dbpath)
            if not os.path.isdir(pkg_dbdir):
                os.makedirs(pkg_dbdir, 0o755)
            # extract edb
            dump_exit_st = entropy.tools.dump_entropy_metadata(
                package_path, pkg_dbpath)
            if not dump_exit_st:
                # error during entropy db extraction from package file
                # might be because edb entry point is not found or
                # because there is not enough space for it
                self._entropy.logger.log(
                    "[Package]", etpConst['logging']['normal_loglevel_id'],
                    "Unable to dump edb for: " + pkg_dbpath
                )
                self._entropy.output(
                    brown(_("Unable to find Entropy metadata in package")),
                    importance = 1,
                    level = "error",
                    header = red("   ## ")
                )
                return 1

        try:
            exit_st = entropy.tools.uncompress_tarball(
                package_path,
                extract_path = image_dir,
                catch_empty = True
            )
        except EOFError as err:
            self._entropy.logger.log(
                "[Package]", etpConst['logging']['normal_loglevel_id'],
                "EOFError on " + package_path + " " + \
                repr(err)
            )
            entropy.tools.print_traceback()
            # try again until unpack_tries goes to 0
            exit_st = 1
        except Exception as err:
            self._entropy.logger.log(
                "[Package]",
                etpConst['logging']['normal_loglevel_id'],
                "Ouch! error while unpacking " + \
                package_path + " " + repr(err)
            )
            entropy.tools.print_traceback()
            # try again until unpack_tries goes to 0
            exit_st = 1

        if exit_st != 0:
            self._entropy.logger.log(
                "[Package]", etpConst['logging']['normal_loglevel_id'],
                "Unable to unpack: %s" % (package_path,)
            )
            self._entropy.output(
                brown(_("Unable to unpack package")),
                importance = 1,
                level = "error",
                header = red("   ## ")
            )

        return exit_st

    def _fill_image_dir(self, merge_from, image_dir):
        """
        Fill the image directory with content from a filesystme path.
        """
        repo = self._entropy.open_repository(self._repository_id)
        # this is triggered by merge_from pkgmeta metadata
        # even if repositories are allowed to not have content
        # metadata, in this particular case, it is mandatory
        contents = repo.retrieveContentIter(
            self._package_id,
            order_by = "file")

        for path, ftype in contents:
            # convert back to filesystem str
            encoded_path = path
            path = os.path.join(merge_from, encoded_path[1:])
            topath = os.path.join(image_dir, encoded_path[1:])
            path = const_convert_to_rawstring(path)
            topath = const_convert_to_rawstring(topath)

            try:
                exist = os.lstat(path)
            except OSError:
                continue # skip file

            if "dir" == ftype and \
                not stat.S_ISDIR(exist.st_mode) and \
                os.path.isdir(path):
                # workaround for directory symlink issues
                path = os.path.realpath(path)

            copystat = False
            # if our directory is a symlink instead, then copy the symlink
            if os.path.islink(path):
                tolink = os.readlink(path)
                if os.path.islink(topath):
                    os.remove(topath)
                os.symlink(tolink, topath)
            elif os.path.isdir(path):
                if not os.path.isdir(topath):
                    os.makedirs(topath)
                    copystat = True
            elif os.path.isfile(path):
                if os.path.isfile(topath):
                    os.remove(topath) # should never happen
                shutil.copy2(path, topath)
                copystat = True

            if copystat:
                user = os.stat(path)[stat.ST_UID]
                group = os.stat(path)[stat.ST_GID]
                os.chown(topath, user, group)
                shutil.copystat(path, topath)

    def _merge(self):
        """
        Execute the merge (from) phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Merging"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        txt = "%s: %s" % (
            blue(_("Merging package")),
            red(self._meta['atom']),
        )
        self._entropy.output(
            txt,
            importance = 1,
            level = "info",
            header = red("   ## ")
        )
        self._entropy.logger.log(
            "[Package]",
            etpConst['logging']['normal_loglevel_id'],
            "Merging package: %s" % (self._meta['atom'],)
        )

        self._fill_image_dir(self._meta['merge_from'],
            self._meta['imagedir'])
        spm_class = self._entropy.Spm_class()
        return spm_class.entropy_install_unpack_hook(self._entropy,
            self._meta)

    def _unpack(self):
        """
        Execute the unpack phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Unpacking"),
            self._meta['download'],
        )
        self._entropy.set_title(xterm_title)

        unpack_dir = self._meta['unpackdir']

        if not const_is_python3():
            # unpackdir comes from download metadatum, which is utf-8
            # (conf_encoding)
            unpack_dir = const_convert_to_rawstring(unpack_dir,
                from_enctype = etpConst['conf_encoding'])

        if os.path.isdir(unpack_dir):
            # this, if Python 2.x, must be fed with rawstrings
            shutil.rmtree(unpack_dir)
        elif os.path.isfile(unpack_dir):
            os.remove(unpack_dir)
        os.makedirs(unpack_dir)

        exit_st = self._unpack_package(
            self._meta['download'], self._meta['pkgpath'],
            self._meta['imagedir'], self._meta['pkgdbpath'])

        if exit_st == 0:
            for extra_download in self._meta['extra_download']:
                download = extra_download['download']
                pkgpath = self.get_standard_fetch_disk_path(download)
                exit_st = self._unpack_package(download, pkgpath,
                    self._meta['imagedir'], None)
                if exit_st != 0:
                    break

        if exit_st != 0:
            if exit_st == 512:
                errormsg = "%s. %s. %s: 512" % (
                    red(_("You are running out of disk space")),
                    red(_("I bet, you're probably Michele")),
                    blue(_("Error")),
                )
            else:
                msg = _("An error occured while trying to unpack the package")
                errormsg = "%s. %s. %s: %s" % (
                    red(msg),
                    red(_("Check if your system is healthy")),
                    blue(_("Error")),
                    exit_st,
                )
            self._entropy.output(
                errormsg,
                importance = 1,
                level = "error",
                header = red("   ## ")
            )
            return exit_st

        spm_class = self._entropy.Spm_class()
        # call Spm unpack hook
        return spm_class.entropy_install_unpack_hook(self._entropy,
            self._meta)

    def _setup(self):
        """
        Execute the setup phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Setup"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        exit_st = 0
        data = self._meta['triggers'].get('install')
        action_data = self._meta['triggers'].get('install')

        if data:
            trigger = self._entropy.Triggers(
                self.NAME, "setup",
                data, action_data)
            ack = trigger.prepare()
            if ack:
                exit_st = trigger.run()
            trigger.kill()

        if exit_st != 0:
            return exit_st

        # NOTE: fixup permissions in the image directory
        # the setup phase could have created additional users and groups
        package_path = self._meta['pkgpath']
        prefix_dir = self._meta['imagedir']
        try:
            entropy.tools.apply_tarball_ownership(package_path, prefix_dir)
        except IOError as err:
            msg = "%s: %s" % (
                brown(_("Error during package files permissions setup")),
                err,)
            self._entropy.output(
                msg,
                importance = 1,
                level = "error",
                header = darkred(" !!! ")
            )
            exit_st = 1

        return exit_st

    def _pre_install(self):
        """
        Execute the pre-install phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Pre-install"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        data = self._meta['triggers'].get('install')
        action_data = self._meta['triggers'].get('install')
        exit_st = 0

        if data:
            trigger = self._entropy.Triggers(
                self.NAME, "preinstall",
                data, action_data)
            ack = trigger.prepare()
            if ack:
                exit_st = trigger.run()
            trigger.kill()

        return exit_st

    def _pre_remove(self):
        """
        Execute the pre-remove phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Pre-remove"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        data = self._meta['triggers'].get('remove')
        action_data = self._meta['triggers'].get('install')
        exit_st = 0

        if data:
            trigger = self._entropy.Triggers(
                self.NAME, "preremove", data,
                action_data)
            ack = trigger.prepare()
            if ack:
                exit_st = trigger.run()
            trigger.kill()

        return exit_st

    def _install_clean(self):
        """
        Cleanup package files not used anymore by newly installed version.
        This is part of the atomic install, which overwrites the live fs with
        new files and removes old afterwards.
        """
        self._entropy.output(
            blue(_("Cleaning previously installed application data.")),
            importance = 1,
            level = "info",
            header = red("   ## ")
        )

        installed_repository = self._entropy.installed_repository()

        preserved_mgr = preservedlibs.PreservedLibraries(
            installed_repository, self._meta['installed_package_id'],
            self._meta['removed_libs'],
            root = self._get_system_root(self._meta))

        self._remove_content_from_system(
            installed_repository,
            self._meta['already_protected_config_files'],
            preserved_mgr
            )

        # garbage collect preserved libraries that are no longer needed
        self._garbage_collect_preserved_libs(preserved_mgr)

        return 0

    def _preserved_libs_gc(self):
        """
        Execute the garbage collection of preserved libraries.
        """
        installed_repository = self._entropy.installed_repository()

        # NOTE: removed_libs is always empty because this phase is only
        # called when remove_package_id == -1
        preserved_mgr = preservedlibs.PreservedLibraries(
            installed_repository, self._meta['installed_package_id'],
            self._meta['removed_libs'],
            root = self._get_system_root(self._meta))

        self._garbage_collect_preserved_libs(preserved_mgr)

        return 0

    def _post_remove(self):
        """
        Execute the post-remove phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Post-remove"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        data = self._meta['triggers'].get('remove')
        action_data = self._meta['triggers'].get('install')
        exit_st = 0

        if data:
            trigger = self._entropy.Triggers(
                self.NAME, "postremove", data,
                action_data)
            ack = trigger.prepare()
            if ack:
                exit_st = trigger.run()
            trigger.kill()

        return exit_st

    def _post_remove_install(self):
        """
        Execute the post-remove SPM package metadata phase.
        """
        self._entropy.logger.log(
            "[Package]",
            etpConst['logging']['normal_loglevel_id'],
            "Remove old package (spm data): %s" % (self._meta['removeatom'],)
        )
        return self._spm_remove_package(self._meta['removeatom'])

    def _install_spm(self):
        """
        Execute the installation of SPM package metadata.
        """
        spm = self._entropy.Spm()

        self._entropy.logger.log(
            "[Package]",
            etpConst['logging']['normal_loglevel_id'],
            "Installing new SPM entry: %s" % (self._meta['atom'],)
        )

        # this comes from _add_installed_package()
        installed_package_id = self._meta['installed_package_id']

        spm_uid = spm.add_installed_package(self._meta)
        inst_repo = self._entropy.installed_repository()
        if spm_uid != -1:
            inst_repo.insertSpmUid(installed_package_id, spm_uid)

        return 0

    def _post_install(self):
        """
        Execute the post-install phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Post-install"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        data = self._meta['triggers'].get('install')
        action_data = self._meta['triggers'].get('install')
        exit_st = 0

        if data:
            trigger = self._entropy.Triggers(
                self.NAME, "postinstall",
                data, action_data)
            ack = trigger.prepare()
            if ack:
                exit_st = trigger.run()
            trigger.kill()

        return exit_st

    def _cleanup(self):
        """
        Execute the cleanup phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Cleaning"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        txt = "%s: %s" % (
            blue(_("Cleaning")),
            red(self._meta['atom']),
        )
        self._entropy.output(
            txt,
            importance = 1,
            level = "info",
            header = red("   ## ")
        )

        # shutil.rmtree wants raw strings, otherwise it will explode
        unpack_dir = const_convert_to_rawstring(self._meta['unpackdir'])

        # best-effort below.
        try:
            shutil.rmtree(unpack_dir, True)
        except shutil.Error as err:
            self._entropy.logger.log(
                "[Package]", etpConst['logging']['normal_loglevel_id'],
                "WARNING!!! Failed to cleanup directory %s," \
                " error: %s" % (unpack_dir, err,))
        try:
            os.rmdir(unpack_dir)
        except OSError:
            pass

        return 0

    def _filter_out_files_installed_on_diff_path(self, content_file,
                                                 installed_content):
        """
        Use case: if a package provided files in /lib then, a new version
        of that package moved the same files under /lib64, we need to check
        if both directory paths solve to the same inode and if so,
        add to our set that we're going to return.
        """
        sys_root = self._get_system_root(self._meta)
        second_pass_removal = set()

        if not installed_content:
            # nothing to filter, no-op
            return
        def _main_filter(_path):
            item_dir = os.path.dirname("%s%s" % (
                    sys_root, _path,))
            item = os.path.join(
                os.path.realpath(item_dir),
                os.path.basename(_path))
            if item in installed_content:
                second_pass_removal.add(item)
                return False
            return True

        # first pass, remove direct matches, schedule a second pass
        # list of files
        Content.filter_content_file(content_file, _main_filter)

        if not second_pass_removal:
            # done then
            return

        # second pass, drop remaining files
        # unfortunately, this is the only way to work it out
        # with iterators
        def _filter(_path):
            return _path not in second_pass_removal
        Content.filter_content_file(content_file, _filter)

    def _add_installed_package(self, items_installed, items_not_installed):
        """
        For internal use only.
        Copy package from repository to installed packages one.
        """
        def _merge_removecontent(inst_repo, repo, _package_id):
            # NOTE: this could be a source of memory consumption
            # but generally, the difference between two contents
            # is really small
            content_diff = list(inst_repo.contentDiff(
                self._meta['remove_package_id'],
                repo,
                _package_id,
                extended=True))

            if content_diff:

                # reverse-order compare
                def _cmp_func(_path, _spath):
                    if _path > _spath:
                        return -1
                    elif _path == _spath:
                        return 0
                    return 1

                # must be sorted, and in reverse order
                # or the merge step won't work
                content_diff.sort(reverse=True)

                Content.merge_content_file(
                    self._meta['removecontent_file'],
                    content_diff, _cmp_func)

        inst_repo = self._entropy.installed_repository()
        smart_pkg = self._meta['smartpackage']
        repo = self._entropy.open_repository(self._repository_id)

        splitdebug, splitdebug_dirs = (
            self._meta['splitdebug'],
            self._meta['splitdebug_dirs'])

        if smart_pkg or self._meta['merge_from']:

            data = repo.getPackageData(self._package_id,
                content_insert_formatted = True,
                get_changelog = False, get_content = False,
                get_content_safety = False)

            content = repo.retrieveContentIter(
                self._package_id)
            content_file = self._generate_content_file(
                content, package_id = self._package_id,
                filter_splitdebug = True,
                splitdebug = splitdebug,
                splitdebug_dirs = splitdebug_dirs)

            content_safety = repo.retrieveContentSafetyIter(
                self._package_id)
            content_safety_file = self._generate_content_safety_file(
                content_safety)

            if self._meta['remove_package_id'] != -1 and \
                    self._meta['removecontent_file'] is not None:
                _merge_removecontent(
                    inst_repo, repo, self._package_id)

        else:

            # normal repositories
            data = repo.getPackageData(self._package_id,
                get_content = False, get_changelog = False)

            # indexing_override = False : no need to index tables
            # xcache = False : no need to use on-disk cache
            # skipChecks = False : creating missing tables is unwanted,
            # and also no foreign keys update
            # readOnly = True: no need to open in write mode
            pkg_repo = self._entropy.open_generic_repository(
                self._meta['pkgdbpath'], skip_checks = True,
                indexing_override = False, read_only = True,
                xcache = False)

            # it is safe to consider that package dbs coming from repos
            # contain only one entry
            pkg_package_id = sorted(pkg_repo.listAllPackageIds(),
                reverse = True)[0]
            content = pkg_repo.retrieveContentIter(
                pkg_package_id)
            content_file = self._generate_content_file(
                content, package_id = self._package_id,
                filter_splitdebug = True,
                splitdebug = splitdebug,
                splitdebug_dirs = splitdebug_dirs)

            # setup content safety metadata, get from package
            content_safety = pkg_repo.retrieveContentSafetyIter(
                pkg_package_id)
            content_safety_file = self._generate_content_safety_file(
                content_safety)

            if self._meta['remove_package_id'] != -1 and \
                    self._meta['removecontent_file'] is not None:
                _merge_removecontent(inst_repo, pkg_repo, pkg_package_id)

            pkg_repo.close()

        # items_installed is useful to avoid the removal of installed
        # files by __remove_package just because
        # there's a difference in the directory path, perhaps,
        # which is not handled correctly by
        # EntropyRepository.contentDiff for obvious reasons
        # (think about stuff in /usr/lib and /usr/lib64,
        # where the latter is just a symlink to the former)
        # --
        # fix removecontent, need to check if we just installed files
        # that resolves at the same directory path (different symlink)
        if self._meta['removecontent_file'] is not None:
            self._filter_out_files_installed_on_diff_path(
                self._meta['removecontent_file'],
                items_installed)

        # filter out files not installed from content metadata
        # these include splitdebug files, when splitdebug is
        # disabled.
        if items_not_installed:
            def _filter(_path):
                return _path not in items_not_installed
            Content.filter_content_file(
                content_file, _filter)

        # this is needed to make postinstall trigger work properly
        self._meta['triggers']['install']['affected_directories'] = \
            self._meta['affected_directories']
        self._meta['triggers']['install']['affected_infofiles'] = \
            self._meta['affected_infofiles']

        # always set data['injected'] to False
        # installed packages database SHOULD never have more
        # than one package for scope (key+slot)
        data['injected'] = False
        # spm counter will be set in self._install_package_into_spm_database()
        data['counter'] = -1
        # branch must be always set properly, it could happen it's not
        # when installing packages through their .tbz2s
        data['branch'] = self._settings['repositories']['branch']
        # there is no need to store needed paths into db
        if "needed_paths" in data:
            del data['needed_paths']
        # there is no need to store changelog data into db
        if "changelog" in data:
            del data['changelog']
        # we don't want it to be added now, we want to add install source
        # info too.
        if "original_repository" in data:
            del data['original_repository']
        # rewrite extra_download metadata with the currently provided,
        # and accepted extra_download items (in case of splitdebug being
        # disable, we're not going to add those entries, for example)
        data['extra_download'] = self._meta['extra_download']

        data['content'] = None
        data['content_safety'] = None
        try:
            # now we are ready to craft a 'content' iter object
            data['content'] = Content.FileContentReader(
                content_file)
            data['content_safety'] = Content.FileContentSafetyReader(
                content_safety_file)
            package_id = inst_repo.handlePackage(
                data, revision = data['revision'],
                formattedContent = True)
        finally:
            if data['content'] is not None:
                try:
                    data['content'].close()
                    data['content'] = None
                except (OSError, IOError):
                    data['content'] = None
            if data['content_safety'] is not None:
                try:
                    data['content_safety'].close()
                    data['content_safety'] = None
                except (OSError, IOError):
                    data['content_safety'] = None

        # update datecreation
        ctime = time.time()
        inst_repo.setCreationDate(package_id, str(ctime))

        # add idpk to the installedtable
        inst_repo.dropInstalledPackageFromStore(package_id)
        inst_repo.storeInstalledPackage(package_id,
            self._repository_id, self._meta['install_source'])

        automerge_data = self._meta.get('configprotect_data')
        if automerge_data:
            inst_repo.insertAutomergefiles(package_id, automerge_data)

        inst_repo.commit()

        # replace current empty "content" metadata info
        # content metadata is required by
        # _spm_install_package() -> Spm.add_installed_package()
        # in case of injected packages (SPM metadata might be
        # incomplete).
        self._meta['triggers']['install']['content'] = \
            Content.FileContentReader(content_file)

        return package_id

    def _install_package(self):
        """
        Execute the package installation code.
        """
        # clear on-disk cache
        self._entropy.clear_cache()

        self._entropy.logger.log(
            "[Package]",
            etpConst['logging']['normal_loglevel_id'],
            "Installing package: %s" % (self._meta['atom'],)
        )

        inst_repo = self._entropy.installed_repository()

        if self._meta['remove_package_id'] != -1:
            am_files = inst_repo.retrieveAutomergefiles(
                self._meta['remove_package_id'],
                get_dict = True)
            self._meta['already_protected_config_files'] = am_files

        # items_*installed will be filled by _move_image_to_system
        # then passed to _add_installed_package()
        items_installed = set()
        items_not_installed = set()
        exit_st = self._move_image_to_system(
            items_installed, items_not_installed)
        if exit_st != 0:
            return exit_st

        txt = "%s: %s" % (
            blue(_("Updating installed packages repository")),
            teal(self._meta['atom']),
        )
        self._entropy.output(
            txt,
            importance = 1,
            level = "info",
            header = red("   ## ")
        )
        self._meta['installed_package_id'] = self._add_installed_package(
            items_installed, items_not_installed)

        return 0

    def _install(self):
        """
        Execute the install phase.
        """
        xterm_title = "%s %s: %s" % (
            self._xterm_header,
            _("Installing"),
            self._meta['atom'],
        )
        self._entropy.set_title(xterm_title)

        txt = "%s: %s" % (
            blue(_("Installing package")),
            red(self._meta['atom']),
        )
        self._entropy.output(
            txt,
            importance = 1,
            level = "info",
            header = red("   ## ")
        )

        self._entropy.output(
            "[%s]" % (
                purple(self._meta['description']),
            ),
            importance = 1,
            level = "info",
            header = red("   ## ")
        )

        if self._meta['splitdebug']:
            if self._meta.get('splitdebug_pkgfile'):
                txt = "[%s]" % (
                    teal(_("unsupported splitdebug usage (package files)")),)
                level = "warning"
            else:
                txt = "[%s]" % (
                    teal(_("<3 debug files installation enabled <3")),)
                level = "info"
            self._entropy.output(
                txt,
                importance = 1,
                level = level,
                header = red("   ## ")
            )

        exit_st = self._install_package()
        if exit_st != 0:
            txt = "%s. %s. %s: %s" % (
                red(_("An error occured while trying to install the package")),
                red(_("Check if your system is healthy")),
                blue(_("Error")),
                exit_st,
            )
            self._entropy.output(
                txt,
                importance = 1,
                level = "error",
                header = red("   ## ")
            )
        return exit_st

    def _handle_install_collision_protect(self, tofile, todbfile):
        """
        Handle files collition protection for the install phase.
        """
        inst_repo = self._entropy.installed_repository()
        avail = inst_repo.isFileAvailable(
            const_convert_to_unicode(todbfile), get_id = True)

        if (self._meta['remove_package_id'] not in avail) and avail:
            mytxt = darkred(_("Collision found during install for"))
            mytxt += " %s - %s" % (
                blue(tofile),
                darkred(_("cannot overwrite")),
            )
            self._entropy.output(
                red("QA: ")+mytxt,
                importance = 1,
                level = "warning",
                header = darkred("   ## ")
            )
            self._entropy.logger.log(
                "[Package]",
                etpConst['logging']['normal_loglevel_id'],
                "WARNING!!! Collision found during install " \
                "for %s - cannot overwrite" % (tofile,)
            )
            return False

        return True

    def _move_image_to_system(self, items_installed, items_not_installed):
        """
        Internal method that moves the package image directory to the live
        filesystem.
        """
        metadata = self.metadata()
        repo = self._entropy.open_repository(self._repository_id)
        protect = self._get_config_protect(repo, self._package_id)
        mask = self._get_config_protect(repo, self._package_id,
                                        mask = True)
        protectskip = self._get_config_protect_skip()

        # support for unit testing settings
        sys_root = self._get_system_root(metadata)
        sys_set_plg_id = \
            etpConst['system_settings_plugins_ids']['client_plugin']
        misc_data = self._settings[sys_set_plg_id]['misc']
        col_protect = misc_data['collisionprotect']
        splitdebug, splitdebug_dirs = metadata['splitdebug'], \
            metadata['splitdebug_dirs']
        info_dirs = self._get_info_directories()

        # setup image_dir properly
        image_dir = metadata['imagedir'][:]
        if not const_is_python3():
            # image_dir comes from unpackdir, which comes from download
            # metadatum, which is utf-8 (conf_encoding)
            image_dir = const_convert_to_rawstring(image_dir,
                from_enctype = etpConst['conf_encoding'])
        movefile = entropy.tools.movefile

        def workout_subdir(currentdir, subdir):

            imagepath_dir = os.path.join(currentdir, subdir)
            rel_imagepath_dir = imagepath_dir[len(image_dir):]
            rootdir = sys_root + rel_imagepath_dir

            # splitdebug (.debug files) support
            # If splitdebug is not enabled, do not create splitdebug directories
            # and move on instead (return)
            if not splitdebug:
                for split_dir in splitdebug_dirs:
                    if rootdir.startswith(split_dir):
                        # also drop item from content metadata. In this way
                        # SPM has in sync information on what the package
                        # content really is.
                        # ---
                        # we should really use unicode
                        # strings for items_not_installed
                        unicode_rootdir = const_convert_to_unicode(rootdir)
                        items_not_installed.add(unicode_rootdir)
                        return

            # handle broken symlinks
            if os.path.islink(rootdir) and not os.path.exists(rootdir):
                # broken symlink
                os.remove(rootdir)

            # if our directory is a file on the live system
            elif os.path.isfile(rootdir): # really weird...!

                self._entropy.logger.log(
                    "[Package]",
                    etpConst['logging']['normal_loglevel_id'],
                    "WARNING!!! %s is a file when it should be " \
                    "a directory !! Removing in 20 seconds..." % (rootdir,)
                )
                mytxt = darkred(_("%s is a file when should be a " \
                "directory !! Removing in 20 seconds...") % (rootdir,))

                self._entropy.output(
                    red("QA: ")+mytxt,
                    importance = 1,
                    level = "warning",
                    header = red(" !!! ")
                )
                os.remove(rootdir)

            # if our directory is a symlink instead, then copy the symlink
            if os.path.islink(imagepath_dir):

                # if our live system features a directory instead of
                # a symlink, we should consider removing the directory
                if not os.path.islink(rootdir) and os.path.isdir(rootdir):
                    self._entropy.logger.log(
                        "[Package]",
                        etpConst['logging']['normal_loglevel_id'],
                        "WARNING!!! %s is a directory when it should be " \
                        "a symlink !! Removing in 20 seconds..." % (
                            rootdir,)
                    )
                    mytxt = "%s: %s" % (
                        _("directory expected, symlink found"),
                        rootdir,
                    )
                    mytxt2 = _("Removing in 20 seconds !!")
                    for txt in (mytxt, mytxt2,):
                        self._entropy.output(
                            darkred("QA: ") + darkred(txt),
                            importance = 1,
                            level = "warning",
                            header = red(" !!! ")
                        )

                    # fucking kill it in any case!
                    # rootdir must die! die die die die!
                    # /me brings chainsaw
                    try:
                        shutil.rmtree(rootdir, True)
                    except (shutil.Error, OSError,) as err:
                        self._entropy.logger.log(
                            "[Package]",
                            etpConst['logging']['normal_loglevel_id'],
                            "WARNING!!! Failed to rm %s " \
                            "directory ! [workout_subdir/1]: %s" % (
                                rootdir, err,
                            )
                        )

                tolink = os.readlink(imagepath_dir)
                live_tolink = None
                if os.path.islink(rootdir):
                    live_tolink = os.readlink(rootdir)

                if tolink != live_tolink:
                    _symfail = False
                    if os.path.lexists(rootdir):
                        # at this point, it must be a file
                        try:
                            os.remove(rootdir)
                        except OSError as err:
                            _symfail = True
                            # must be atomic, too bad if it fails
                            self._entropy.logger.log(
                                "[Package]",
                                etpConst['logging']['normal_loglevel_id'],
                                "WARNING!!! Failed to remove %s " \
                                "file ! [workout_file/0]: %s" % (
                                    rootdir, err,
                                )
                            )
                            msg = _("Cannot remove symlink")
                            mytxt = "%s: %s => %s" % (
                                purple(msg),
                                blue(rootdir),
                                repr(err),
                            )
                            self._entropy.output(
                                mytxt,
                                importance = 1,
                                level = "warning",
                                header = brown("   ## ")
                            )
                    if not _symfail:
                        os.symlink(tolink, rootdir)

            elif not os.path.isdir(rootdir):
                # directory not found, we need to create it

                try:
                    # really force a simple mkdir first of all
                    os.mkdir(rootdir)
                except OSError:
                    os.makedirs(rootdir)


            if not os.path.islink(rootdir):

                # symlink doesn't need permissions, also
                # until os.walk ends they might be broken
                user = os.stat(imagepath_dir)[stat.ST_UID]
                group = os.stat(imagepath_dir)[stat.ST_GID]
                try:
                    os.chown(rootdir, user, group)
                    shutil.copystat(imagepath_dir, rootdir)
                except (OSError, IOError) as err:
                    self._entropy.logger.log(
                        "[Package]",
                        etpConst['logging']['normal_loglevel_id'],
                        "Error during workdir setup " \
                        "%s, %s, errno: %s" % (
                                rootdir,
                                err,
                                err.errno,
                            )
                    )
                    # skip some errors because we may have
                    # unwritable directories
                    if err.errno not in (
                            errno.EPERM, errno.ENOENT,
                            errno.ENOTDIR):
                        mytxt = "%s: %s, %s, %s" % (
                            brown("Error during workdir setup"),
                            purple(rootdir), err,
                            err.errno
                        )
                        self._entropy.output(
                            mytxt,
                            importance = 1,
                            level = "error",
                            header = darkred(" !!! ")
                        )
                        return 4

            item_dir, item_base = os.path.split(rootdir)
            item_dir = os.path.realpath(item_dir)
            item_inst = os.path.join(item_dir, item_base)
            item_inst = const_convert_to_unicode(item_inst)
            items_installed.add(item_inst)


        def workout_file(currentdir, item):

            fromfile = os.path.join(currentdir, item)
            rel_fromfile = fromfile[len(image_dir):]
            rel_fromfile_dir = os.path.dirname(rel_fromfile)
            tofile = sys_root + rel_fromfile

            rel_fromfile_dir_utf = const_convert_to_unicode(
                rel_fromfile_dir)
            metadata['affected_directories'].add(
                rel_fromfile_dir_utf)

            # account for info files, if any
            if rel_fromfile_dir_utf in info_dirs:
                rel_fromfile_utf = const_convert_to_unicode(
                    rel_fromfile)
                for _ext in self._INFO_EXTS:
                    if rel_fromfile_utf.endswith(_ext):
                        metadata['affected_infofiles'].add(
                            rel_fromfile_utf)
                        break

            # splitdebug (.debug files) support
            # If splitdebug is not enabled, do not create
            # splitdebug directories and move on instead (return)
            if not splitdebug:
                for split_dir in splitdebug_dirs:
                    if tofile.startswith(split_dir):
                        # also drop item from content metadata. In this way
                        # SPM has in sync information on what the package
                        # content really is.
                        # ---
                        # we should really use unicode
                        # strings for items_not_installed
                        unicode_tofile = const_convert_to_unicode(tofile)
                        items_not_installed.add(unicode_tofile)
                        return 0

            if col_protect > 1:
                todbfile = fromfile[len(image_dir):]
                myrc = self._handle_install_collision_protect(tofile,
                    todbfile)
                if not myrc:
                    return 0

            prot_old_tofile = tofile[len(sys_root):]
            # configprotect_data is passed to insertAutomergefiles()
            # which always expects unicode data.
            # revert back to unicode (we previously called encode on
            # image_dir (which is passed to os.walk, which generates
            # raw strings)
            prot_old_tofile = const_convert_to_unicode(prot_old_tofile)

            pre_tofile = tofile[:]
            (in_mask, protected,
             tofile, do_return) = self._handle_config_protect(
                 protect, mask, protectskip, fromfile, tofile)

            # collect new config automerge data
            if in_mask and os.path.exists(fromfile):
                try:
                    prot_md5 = const_convert_to_unicode(
                        entropy.tools.md5sum(fromfile))
                    metadata['configprotect_data'].append(
                        (prot_old_tofile, prot_md5,))
                except (IOError,) as err:
                    self._entropy.logger.log(
                        "[Package]",
                        etpConst['logging']['normal_loglevel_id'],
                        "WARNING!!! Failed to get md5 of %s " \
                        "file ! [workout_file/1]: %s" % (
                            fromfile, err,
                        )
                    )

            # check if it's really necessary to protect file
            if protected:

                # second task
                # prot_old_tofile is always unicode, it must be, see above
                oldprot_md5 = metadata['already_protected_config_files'].get(
                    prot_old_tofile)

                if oldprot_md5:

                    try:
                        in_system_md5 = entropy.tools.md5sum(pre_tofile)
                    except (OSError, IOError) as err:
                        if err.errno != errno.ENOENT:
                            raise
                        in_system_md5 = "?"

                    if oldprot_md5 == in_system_md5:
                        # we can merge it, files, even if
                        # contains changes have not been modified
                        # by the user
                        msg = _("Automerging config file, never modified")
                        mytxt = "%s: %s" % (
                            darkgreen(msg),
                            blue(pre_tofile),
                        )
                        self._entropy.output(
                            mytxt,
                            importance = 1,
                            level = "info",
                            header = red("   ## ")
                        )
                        protected = False
                        do_return = False
                        tofile = pre_tofile

            if do_return:
                return 0

            try:
                from_r_path = os.path.realpath(fromfile)
            except RuntimeError:
                # circular symlink, fuck!
                # really weird...!
                self._entropy.logger.log(
                    "[Package]",
                    etpConst['logging']['normal_loglevel_id'],
                    "WARNING!!! %s is a circular symlink !!!" % (fromfile,)
                )
                mytxt = "%s: %s" % (
                    _("Circular symlink issue"),
                    const_convert_to_unicode(fromfile),
                )
                self._entropy.output(
                    darkred("QA: ") + darkred(mytxt),
                    importance = 1,
                    level = "warning",
                    header = red(" !!! ")
                )
                from_r_path = fromfile

            try:
                to_r_path = os.path.realpath(tofile)
            except RuntimeError:
                # circular symlink, fuck!
                # really weird...!
                self._entropy.logger.log(
                    "[Package]",
                    etpConst['logging']['normal_loglevel_id'],
                    "WARNING!!! %s is a circular symlink !!!" % (tofile,)
                )
                mytxt = "%s: %s" % (
                    _("Circular symlink issue"),
                    const_convert_to_unicode(tofile),
                )
                self._entropy.output(
                    darkred("QA: ") + darkred(mytxt),
                    importance = 1,
                    level = "warning",
                    header = red(" !!! ")
                )
                to_r_path = tofile

            if from_r_path == to_r_path and os.path.islink(tofile):
                # there is a serious issue here, better removing tofile,
                # happened to someone.

                try:
                    # try to cope...
                    os.remove(tofile)
                except (OSError, IOError,) as err:
                    self._entropy.logger.log(
                        "[Package]",
                        etpConst['logging']['normal_loglevel_id'],
                        "WARNING!!! Failed to cope to oddity of %s " \
                        "file ! [workout_file/2]: %s" % (
                            tofile, err,
                        )
                    )

            # if our file is a dir on the live system
            if os.path.isdir(tofile) and not os.path.islink(tofile):

                # really weird...!
                self._entropy.logger.log(
                    "[Package]",
                    etpConst['logging']['normal_loglevel_id'],
                    "WARNING!!! %s is a directory when it should " \
                    "be a file !! Removing in 20 seconds..." % (tofile,)
                )

                mytxt = "%s: %s" % (
                    _("file expected, directory found"),
                    const_convert_to_unicode(tofile),
                )
                mytxt2 = _("Removing in 20 seconds !!")
                for txt in (mytxt, mytxt2,):
                    self._entropy.output(
                        darkred("QA: ") + darkred(txt),
                        importance = 1,
                        level = "warning",
                        header = red(" !!! ")
                    )

                try:
                    shutil.rmtree(tofile, True)
                except (shutil.Error, IOError,) as err:
                    self._entropy.logger.log(
                        "[Package]",
                        etpConst['logging']['normal_loglevel_id'],
                        "WARNING!!! Failed to cope to oddity of %s " \
                        "file ! [workout_file/3]: %s" % (
                            tofile, err,
                        )
                    )

            # moving file using the raw format
            try:
                done = movefile(fromfile, tofile, src_basedir = image_dir)
            except (IOError,) as err:
                # try to move forward, sometimes packages might be
                # fucked up and contain broken things
                if err.errno not in (errno.ENOENT, errno.EACCES,):
                    raise

                self._entropy.logger.log(
                    "[Package]",
                    etpConst['logging']['normal_loglevel_id'],
                    "WARNING!!! Error during file move" \
                    " to system: %s => %s | IGNORED: %s" % (
                        const_convert_to_unicode(fromfile),
                        const_convert_to_unicode(tofile),
                        err,
                    )
                )
                done = True

            if not done:
                self._entropy.logger.log(
                    "[Package]",
                    etpConst['logging']['normal_loglevel_id'],
                    "WARNING!!! Error during file move" \
                    " to system: %s => %s" % (fromfile, tofile,)
                )
                mytxt = "%s: %s => %s, %s" % (
                    _("File move error"),
                    const_convert_to_unicode(fromfile),
                    const_convert_to_unicode(tofile),
                    _("please report"),
                )
                self._entropy.output(
                    red("QA: ")+darkred(mytxt),
                    importance = 1,
                    level = "warning",
                    header = red(" !!! ")
                )
                return 4

            item_dir = os.path.realpath(os.path.dirname(tofile))
            item_inst = os.path.join(item_dir, os.path.basename(tofile))
            item_inst = const_convert_to_unicode(item_inst)
            items_installed.add(item_inst)

            if protected and \
                    os.getenv("ENTROPY_CLIENT_ENABLE_OLD_FILEUPDATES"):
                # add to disk cache
                file_updates = self._entropy.PackageFileUpdates()
                file_updates.add(tofile, quiet = True)

            return 0

        # merge data into system
        for currentdir, subdirs, files in os.walk(image_dir):

            # create subdirs
            for subdir in subdirs:
                workout_subdir(currentdir, subdir)

            for item in files:
                move_st = workout_file(currentdir, item)
                if move_st != 0:
                    return move_st

        return 0


