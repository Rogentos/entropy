# -*- coding: utf-8 -*-
"""

    @author: Fabio Erculiani <lxnay@sabayon.org>
    @contact: lxnay@sabayon.org
    @copyright: Fabio Erculiani
    @license: GPL-2

    B{Entropy Infrastructure Toolkit}.

"""
import sys
import os
import argparse

from entropy.const import etpConst
from entropy.i18n import _
from entropy.exceptions import PermissionDenied
from entropy.output import print_info, print_error, darkgreen, \
    teal, brown, darkred, bold, purple, blue

from text_tools import print_table

import entropy.tools

from eit.commands.descriptor import EitCommandDescriptor
from eit.commands.command import EitCommand


class EitStatus(EitCommand):
    """
    Main Eit status command.
    """

    NAME = "status"

    def parse(self):
        descriptor = EitCommandDescriptor.obtain_descriptor(
            EitStatus.NAME)
        parser = argparse.ArgumentParser(
            description=descriptor.get_description(),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            prog="%s %s" % (sys.argv[0], EitStatus.NAME))

        parser.add_argument("repo", nargs='?', default=None,
                            metavar="<repo>", help="repository id")

        try:
            nsargs = parser.parse_args(self._args)
        except IOError as err:
            print_error("error: %s" % (err.strerror,))
            return parser.print_help, []

        return self._status, [nsargs.repo]

    def _status(self, repo):
        """
        Status command body.
        """
        server = None
        acquired = False
        try:
            try:
                server = self._entropy(default_repository=repo)
            except PermissionDenied as err:
                print_error(err.value)
                return 1
            acquired = entropy.tools.acquire_entropy_locks(server)
            if not acquired:
                print_error(
                    darkgreen(_("Another Entropy is currently running."))
                )
                return 1
            return self.__status(server)
        finally:
            if server is not None:
                if acquired:
                    entropy.tools.release_entropy_locks(server)
                server.shutdown()

    def __status(self, entropy_server):
         plugin_id = etpConst['system_settings_plugins_ids']['server_plugin']
         repos_data = self._settings()[plugin_id]['server']['repositories']
         repo_id = entropy_server.repository()

         repo_data = repos_data[repo_id]
         repo_rev = entropy_server.local_repository_revision(repo_id)
         store_dir = entropy_server._get_local_store_directory(repo_id)
         upload_basedir = entropy_server._get_local_upload_directory(repo_id)
         upload_files, upload_packages = \
             entropy_server.Mirrors._calculate_local_upload_files(repo_id)
         key_sorter = lambda x: \
             entropy_server.open_repository(x[1]).retrieveAtom(x[0])

         to_be_added, to_be_removed, to_be_injected = \
                 entropy_server.scan_package_changes()

         to_be_added = [x[0] for x in to_be_added]
         to_be_added.sort()

         toc = []

         toc.append("[%s] %s" % (purple(repo_id),
             brown(repo_data['description']),))
         toc.append(("  %s:" % (blue(_("local revision")),),
             str(repo_rev),))

         store_pkgs = []
         if os.path.isdir(store_dir):
             store_pkgs = os.listdir(store_dir)

         toc.append(("  %s:" % (darkgreen(_("stored packages")),),
             str(len(store_pkgs)),))
         for pkg_rel in sorted(store_pkgs):
             toc.append((" ", brown(pkg_rel)))

         toc.append(("  %s:" % (darkgreen(_("upload packages")),),
             str(upload_files),))
         for pkg_rel in sorted(upload_packages):
             toc.append((" ", brown(pkg_rel)))

         unstaged_len = len(to_be_added) + len(to_be_removed) + \
             len(to_be_injected)
         toc.append(("  %s:" % (darkgreen(_("unstaged packages")),),
             str(unstaged_len),))

         print_table(toc)
         del toc[:]
         print_info("")

         def _get_spm_slot_repo(pkg_atom):
             try:
                 spm_slot = entropy_server.Spm(
                     ).get_installed_package_metadata(pkg_atom, "SLOT")
                 spm_repo = entropy_server.Spm(
                     ).get_installed_package_metadata(pkg_atom,
                     "repository")
             except KeyError:
                 spm_repo = None
                 spm_slot = None
             return spm_slot, spm_repo

         for pkg_atom in to_be_added:
             spm_slot, spm_repo = _get_spm_slot_repo(pkg_atom)

             pkg_str = teal(pkg_atom)
             if spm_repo is not None:
                 pkg_id, repo_id = entropy_server.atom_match(pkg_atom,
                     match_slot = spm_slot)
                 if pkg_id != -1:
                     etp_repo = entropy_server.open_repository(
                         repo_id).retrieveSpmRepository(pkg_id)
                     if etp_repo != spm_repo:
                         pkg_str += " [%s=>%s]" % (
                             etp_repo, spm_repo,)
             toc.append(("   %s:" % (purple(_("add")),), teal(pkg_str)))

         for package_id, repo_id in sorted(to_be_removed, key = key_sorter):
             pkg_atom = entropy_server.open_repository(repo_id
                 ).retrieveAtom(package_id)
             toc.append(("   %s:" % (darkred(_("remove")),),
                         brown(pkg_atom)))

         for package_id, repo_id in sorted(to_be_injected,
                 key = key_sorter):
             pkg_atom = entropy_server.open_repository(repo_id
                 ).retrieveAtom( package_id)
             toc.append(("   %s:" % (bold(_("switch injected")),),
                 darkgreen(pkg_atom)))

         print_table(toc)
         return 0

EitCommandDescriptor.register(
    EitCommandDescriptor(
        EitStatus,
        EitStatus.NAME,
        _("show repository status"))
    )