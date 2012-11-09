# -*- coding: utf-8 -*-
"""

    @author: Fabio Erculiani <lxnay@sabayon.org>
    @contact: lxnay@sabayon.org
    @copyright: Fabio Erculiani
    @license: GPL-2

    B{Entropy Command Line Client}.

"""
import argparse
import os
import sys

from entropy.i18n import _
from entropy.const import const_convert_to_unicode
from entropy.output import darkred, darkgreen, blue, bold, teal, purple

import entropy.tools

from solo.commands.descriptor import SoloCommandDescriptor
from solo.commands.install import SoloInstall
from solo.commands.remove import SoloRemove


class SoloUpgrade(SoloInstall, SoloRemove):
    """
    Main Solo Upgrade command.
    """

    NAME = "upgrade"
    ALIASES = ["u"]
    ALLOW_UNPRIVILEGED = False

    INTRODUCTION = """\
Upgrade the system.
"""
    SEE_ALSO = "equo-install(1)"

    def __init__(self, args):
        SoloInstall.__init__(self, args)
        SoloRemove.__init__(self, args)
        self._commands = {}
        self._check_critical_updates = False

    def _get_parser(self):
        """
        Overridden from SoloCommand.
        """
        _commands = {}

        descriptor = SoloCommandDescriptor.obtain_descriptor(
            SoloUpgrade.NAME)
        parser = argparse.ArgumentParser(
            description=descriptor.get_description(),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            prog="%s %s" % (sys.argv[0], SoloUpgrade.NAME))
        parser.set_defaults(func=self._upgrade)

        mg_group = parser.add_mutually_exclusive_group()
        mg_group.add_argument(
            "--ask", action="store_true",
            default=False,
            help=_("ask before making any changes"))
        _commands["--ask"] = {}
        mg_group.add_argument(
            "--pretend", action="store_true",
            default=False,
            help=_("show what would be done"))
        _commands["--pretend"] = {}

        parser.add_argument(
            "--verbose", action="store_true",
            default=False,
            help=_("verbose output"))
        parser.add_argument(
            "--quiet", action="store_true",
            default=False,
            help=_("quiet output"))
        parser.add_argument(
            "--fetch", action="store_true",
            default=False,
            help=_("just download packages"))

        parser.add_argument(
            "--bdeps", action="store_true",
            default=False,
            help=_("include build-time dependencies"))
        parser.add_argument(
            "--nodeps", action="store_true",
            default=False,
            help=_("exclude package dependencies"))
        parser.add_argument(
            "--norecursive", action="store_true",
            default=False,
            help=_("do not calculate dependencies recursively"))
        parser.add_argument(
            "--deep", action="store_true",
            default=False,
            help=_("include dependencies no longer needed"))
        parser.add_argument(
            "--empty", action="store_true",
            default=False,
            help=_("when used with --deep, include virtual packages"))
        parser.add_argument(
            "--configfiles", action="store_true",
            default=False,
            help=_("remove package configuration files no longer needed"))

        parser.add_argument(
            "--relaxed", action="store_true",
            default=False,
            help=_("relax dependencies constraints during calculation"))
        parser.add_argument(
            "--multifetch",
            type=int, default=1,
            choices=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            help=_("download multiple packages in parallel (max 10)"))

        self._commands = _commands
        return parser

    def bashcomp(self, last_arg):
        """
        Overridden from SoloCommand.
        """
        self._get_parser() # this will generate self._commands
        return self._hierarchical_bashcomp(last_arg, [], self._commands)

    def _upgrade(self, entropy_client):
        """
        Solo Upgrade command.
        """
        deps = not self._nsargs.nodeps
        recursive = not self._nsargs.norecursive
        pretend = self._nsargs.pretend
        ask = self._nsargs.ask
        verbose = self._nsargs.verbose
        quiet = self._nsargs.quiet
        empty = self._nsargs.empty
        config_files = self._nsargs.configfiles
        deep = self._nsargs.deep
        fetch = self._nsargs.fetch
        bdeps = self._nsargs.bdeps
        relaxed = self._nsargs.relaxed
        multifetch = self._nsargs.multifetch

        exit_st, _show_cfgupd = self._upgrade_action(
            entropy_client, deps, recursive,
            pretend, ask, verbose, quiet, empty,
            config_files, deep, fetch, bdeps,
            relaxed, multifetch)
        if _show_cfgupd:
            self._show_config_files_update(entropy_client)
        return exit_st

    def _upgrade_action(self, entropy_client, deps, recursive,
                        pretend, ask, verbose, quiet, empty,
                        config_files, deep, fetch, bdeps,
                        relaxed, multifetch):
        """
        Solo Upgrade action implementation.
        """
        entropy_client.output(
            "%s: " % (blue(_("Calculating System Updates")),),
            darkred(" @@ "))

        with entropy_client.Cacher():
            update, remove, fine, _spm_fine = \
                entropy_client.calculate_updates(empty=empty)

        if verbose or pretend:
            entropy_client.output(
                "%s => %s" % (
                    bold(const_convert_to_unicode(len(update))),
                    darkgreen(_("Packages matching update")),
                ),
                header=darkred(" @@ "))
            entropy_client.output(
                "%s => %s" % (
                    bold(const_convert_to_unicode(len(remove))),
                    darkred(_("Packages matching not available")),
                ),
                header=darkred(" @@ "))
            entropy_client.output(
                "%s => %s" % (
                    bold(const_convert_to_unicode(len(fine))),
                    blue(_("Packages matching already up to date")),
                ),
                header=darkred(" @@ "))

        # disable collisions protection, better
        client_settings = entropy_client.ClientSettings()
        misc_settings = client_settings['misc']
        old_cprotect = misc_settings['collisionprotect']

        try:
            misc_settings['collisionprotect'] = 1
            if update:
                exit_st, _show_cfgupd = self._install_action(
                    entropy_client, deps, recursive,
                    pretend, ask, verbose, quiet, empty,
                    config_files, deep, fetch, bdeps,
                    relaxed, multifetch, [],
                    package_matches=update)
                if exit_st != 0:
                    return exit_st, _show_cfgupd
            else:
                entropy_client.output(
                    "%s." % (
                        blue(_("Nothing to update")),),
                    header=darkred(" @@ "))
        finally:
            misc_settings['collisionprotect'] = old_cprotect

        if not fetch:
            manual_removal, remove = \
                entropy_client.calculate_orphaned_packages()
            remove.sort()
            manual_removal.sort()

            if manual_removal or remove:
                entropy_client.output(
                    "%s." % (
                        blue(_("On the system there are "
                               "packages that are not available "
                               "anymore in the online repositories")),),
                    header=darkred(" @@ "))
                entropy_client.output(
                    blue(_("Even if they are usually harmless, "
                           "it is suggested (after proper verification) "
                           "to remove them.")),
                    header=darkred(" @@ "))

            if manual_removal:
                self._show_removal_info(
                    entropy_client, manual_removal, manual=True)
            if remove:
                self._show_removal_info(entropy_client, remove)

        if remove and not fetch:

            do_run = True
            rc = 1
            if not pretend:

                if self._interactive:
                    rm_options = [_("Yes"), _("No"), _("Selective")]
                    def fake_callback(s):
                        return s

                    input_params = [('answer',
                        ('combo', (_('Repository'), rm_options),),
                            fake_callback, False)]
                    data = entropy_client.input_box(
                        _('Would you like to remove them?'),
                        input_params
                    )
                    if data is None:
                        return 1, False
                    rc = data.get('answer', 2)[0]

                if rc == 2: # no
                    do_run = False

                elif rc == 3: # selective
                    new_remove = []
                    c_repo = entropy_client.installed_repository()
                    for package_id in remove:
                        c_atom = c_repo.retrieveAtom(package_id)
                        if c_atom is None:
                            continue
                        c_atom = purple(c_atom)
                        r_rc = entropy_client.ask_question("[%s] %s" % (
                            c_atom, _("Remove this?"),))
                        if r_rc == _("Yes"):
                            new_remove.append(package_id)
                    remove = new_remove

            if do_run and remove:
                # use pretend
                exit_st, _show_cfgupd = self._remove_action(
                    entropy_client, pretend, ask,
                    deps, deep, empty, recursive,
                    False, True, [], package_ids=remove)
                if exit_st != 0:
                    return exit_st, _show_cfgupd

        else:
            entropy_client.output(
                "%s." % (blue(_("Nothing to remove")),),
                header=darkred(" @@ "))

        # run post-branch upgrade hooks, if needed
        if not pretend:
            # this triggers post-branch upgrade function inside
            # Entropy Client SystemSettings plugin
            entropy_client.Settings().clear()

        if update and not pretend and not fetch:
            # if updates have been installed, check if there are more
            # to come (perhaps critical updates were installed)
            self._upgrade_respawn(entropy_client)

        return exit_st, True

    def _upgrade_respawn(self, entropy_client):
        """
        Respawn the upgrade activity if required.
        """
        # It might be an Entropy bug and Entropy was proritized in the
        # install queue, ignoring the rest of available packages.
        # So, respawning myself again using execvp() should be a much
        # better idea.
        update, _remove, _fine, _spm_fine = \
            entropy_client.calculate_updates()
        if update:
            entropy_client.output(
                "%s." % (
                    purple(_("There are more updates to install, "
                      "reloading Entropy")),),
                header=teal(" @@ "))

            # then spawn a new process
            entropy_client.shutdown()
            # hack to tell the resurrected equo to block on
            # locking acquisition
            os.environ['__EQUO_LOCKS_BLOCKING__'] = "1"
            # we will acquire them again in blocking mode, cross
            # fingers
            entropy.tools.release_entropy_locks(entropy_client)
            os.execvp("equo", sys.argv)


SoloCommandDescriptor.register(
    SoloCommandDescriptor(
        SoloUpgrade,
        SoloUpgrade.NAME,
        _("upgrade the system"))
    )
