# -*- coding: utf-8 -*-
"""

    @author: Fabio Erculiani <lxnay@sabayon.org>
    @contact: lxnay@sabayon.org
    @copyright: Fabio Erculiani
    @license: GPL-2

    B{Entropy Command Line Client}.

"""
import os
import sys
import argparse

from entropy.i18n import _
from entropy.output import darkred, darkgreen, blue

from solo.commands.descriptor import SoloCommandDescriptor
from solo.commands._manage import SoloManage

class SoloDownload(SoloManage):
    """
    Main Solo Download command.
    """

    NAME = "download"
    ALIASES = ["fetch"]
    ALLOW_UNPRIVILEGED = False

    INTRODUCTION = """\
Download packages, essentially.
"""
    SEE_ALSO = "equo-source(1)"

    def __init__(self, args):
        SoloManage.__init__(self, args)
        self._commands = {}

    def _get_parser(self):
        """
        Overridden from SoloCommand.
        """
        _commands = {}

        descriptor = SoloCommandDescriptor.obtain_descriptor(
            SoloDownload.NAME)
        parser = argparse.ArgumentParser(
            description=descriptor.get_description(),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            prog="%s %s" % (sys.argv[0], SoloDownload.NAME))
        parser.set_defaults(func=self._download)

        parser.add_argument(
            "packages", nargs='+',
            metavar="<package>", help=_("package name"))

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
            "--relaxed", action="store_true",
            default=False,
            help=_("calculate dependencies relaxing constraints"))
        parser.add_argument(
            "--bdeps", action="store_true",
            default=False,
            help=_("include build-time dependencies"))

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

    def _download(self, entropy_client):
        """
        Solo Download command.
        """
        ask = self._nsargs.ask
        pretend = self._nsargs.pretend
        verbose = self._nsargs.verbose
        quiet = self._nsargs.quiet
        deep = self._nsargs.deep
        deps = not self._nsargs.nodeps
        recursive = not self._nsargs.norecursive
        relaxed = self._nsargs.relaxed
        bdeps = self._nsargs.bdeps
        multifetch = self._nsargs.multifetch

        packages = self._scan_packages(
            entropy_client, self._nsargs.packages)
        if not packages:
            entropy_client.output(
                "%s." % (
                    darkred(_("No packages found")),),
                level="error", importance=1)
            return 1

        action = darkgreen(_("Package download"))
        exit_st = self._show_packages_info(
            entropy_client, packages, deps,
            ask, pretend, verbose, quiet, action_name=action)
        if exit_st != 0:
            return 1

        run_queue, removal_queue = self._generate_install_queue(
            entropy_client, packages, deps, False, deep, relaxed, bdeps,
            recursive)
        if (run_queue is None) or (removal_queue is None):
            return 1

        if pretend:
            entropy_client.output(
                "%s." % (blue(_("All done")),))
            return 0

        down_data = {}
        exit_st = self._download_packages(
            entropy_client, run_queue, down_data, multifetch,
            True)

        if exit_st == 0:
            self._signal_ugc(entropy_client, down_data)
        return exit_st


SoloCommandDescriptor.register(
    SoloCommandDescriptor(
        SoloDownload,
        SoloDownload.NAME,
        _("download packages, essentially"))
    )
