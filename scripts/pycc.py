#!/usr/bin/env python

"""Python Capability Container start script"""

__author__ = 'Adam R. Smith'
__license__ = 'Apache 2.0'

import argparse
import yaml
from uuid import uuid4

#
# WARNING - DO NOT IMPORT GEVENT OR PYON HERE. IMPORTS **MUST** BE DONE IN THE MAIN()
# DUE TO DAEMONIZATION.
#
# SEE: http://groups.google.com/group/gevent/browse_thread/thread/6223805ffcd5be22?pli=1
#

version = "2.0"     # TODO: extract this from the code once versioning is automated again
description = '''
pyon (ION capability container) v%s
''' % (version)

def setup_ipython(shell_api=None):
    from IPython.config.loader import Config
    cfg = Config()
    shell_config = cfg.InteractiveShellEmbed
    shell_config.prompt_in1 = '><> '
    shell_config.prompt_in2 = '... '
    shell_config.prompt_out = '--> '
    shell_config.confirm_exit = False

    # monkeypatch the ipython inputhook to be gevent-friendly
    import gevent   # should be auto-monkey-patched by pyon already.
    import select
    import sys
    def stdin_ready():
        infds, outfds, erfds = select.select([sys.stdin], [], [], 0)
        if infds:
            return True
        else:
            return False

    def inputhook_gevent():
        try:
            while not stdin_ready():
                gevent.sleep(0.001)
        except KeyboardInterrupt:
            pass

        return 0

    # install the gevent inputhook
    from IPython.lib.inputhook import inputhook_manager
    inputhook_manager.set_inputhook(inputhook_gevent)
    inputhook_manager._current_gui = 'gevent'

    # First import the embeddable shell class
    from IPython.frontend.terminal.embed import InteractiveShellEmbed

    # Update namespace of interactive shell
    # TODO: Cleanup namespace even further
    if shell_api is not None:
        locals().update(shell_api)

    # Now create an instance of the embeddable shell. The first argument is a
    # string with options exactly as you would type them if you were starting
    # IPython at the system command line. Any parameters you want to define for
    # configuration can thus be specified here.
    ipshell = InteractiveShellEmbed(config=cfg,
                           banner1 = \
"""    ____                                ________  _   __   ____________   ____  ___
   / __ \__  ______  ____              /  _/ __ \/ | / /  / ____/ ____/  / __ \|__ \\
  / /_/ / / / / __ \/ __ \   ______    / // / / /  |/ /  / /   / /      / /_/ /__/ /
 / ____/ /_/ / /_/ / / / /  /_____/  _/ // /_/ / /|  /  / /___/ /___   / _, _// __/
/_/    \__, /\____/_/ /_/           /___/\____/_/ |_/   \____/\____/  /_/ |_|/____/
      /____/""",
                           exit_msg = 'Leaving ION shell, shutting down container.')

    ipshell('Pyon - ION R2 CC interactive IPython shell. Type ionhelp() for help')

# From http://stackoverflow.com/questions/6037503/python-unflatten-dict/6037657#6037657
def unflatten(dictionary):
    resultDict = dict()
    for key, value in dictionary.iteritems():
        parts = key.split(".")
        d = resultDict
        for part in parts[:-1]:
            if part not in d:
                d[part] = dict()
            d = d[part]
        d[parts[-1]] = value
    return resultDict
    
def main(opts, *args, **kwargs):
    import threading
    threading.current_thread().name = "CC-Main"

    # The import of pyon.public triggers many module initializers:
    # pyon.core.bootstrap (Config load, logging setup), etc.
    from pyon.public import Container, CFG

    # Check if user opted to override logging config
    if opts.logcfg:
        from pyon.util.config import logging_conf_paths, initialize_logging
        # Re-initialize logging
        logging_conf_paths.append(opts.logcfg)
        initialize_logging()

    from pyon.container.shell_api import get_shell_api
    # Set that system is not testing. We are running as standalone container
    CFG.system.testing = False

    container = Container(*args, **kwargs)

    # start and wait for container to signal ready
    ready = container.start()

    start_ok = True
    error_msg = None

    if opts.proc:
        # One off process
        mod, proc = opts.proc.rsplit('.', 1)
        print "Starting process %s" % opts.proc
        container.spawn_process(proc, mod, proc, process_type='immediate')
        container.stop()
        return

    if opts.rel:
        start_ok = container.start_rel_from_url(opts.rel)
        if not start_ok: error_msg = "Cannot start deploy file '%s'" % opts.rel

    if start_ok:
        if not opts.noshell and not opts.daemon:
            setup_ipython(get_shell_api(container))
        else:
            container.serve_forever()
    else:
        print "ABORTING CONTAINER START - ERROR: %s" % error_msg

    container.stop()

def parse_args(tokens):
    """ Exploit yaml's spectacular type inference (and ensure consistency with config files) """
    args, kwargs = [], {}
    for token in tokens:
        token = token.lstrip('-')
        if '=' in token:
            key,val = token.split('=', 1)
            cfg = unflatten({key: yaml.load(val)})
            kwargs.update(cfg)
        else:
            args.append(yaml.load(token))

    return args, kwargs

def entry():
    #proc_types = GreenProcessSupervisor.type_callables.keys()

    # NOTE: Resist the temptation to add other parameters here! Most container config options
    # should be in the config file (pyon.yml), which can also be specified on the command-line via the extra args

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('-d', '--daemon', action='store_true')
    parser.add_argument('-n', '--noshell', action='store_true')
    parser.add_argument('-r', '--rel', type=str, help='Path to a rel file to launch.')
    parser.add_argument('-l', '--logcfg', type=str, help='Path to logging configuration file.')
    parser.add_argument('-x', '--proc', type=str, help='Qualified name of process to start and then exit.')
    parser.add_argument('-p', '--pidfile', type=str, help='PID file to use when --daemon specified. Defaults to cc-<rand>.pid')
    parser.add_argument('-v', '--version', action='version', version='pyon v%s' % (version))
    opts, extra = parser.parse_known_args()
    args, kwargs = parse_args(extra)

    if opts.daemon:
        # TODO: The daemonizing code may need to be moved inside the Container class (so it happens per-process)
        from daemon import DaemonContext
        from lockfile import FileLock

        #logg = open('hi.txt', 'w+')
        #slogg = open('hi2.txt', 'w+')

        # TODO: May need to generate a pidfile based on some parameter or cc name
        pidfile = opts.pidfile or 'cc-%s.pid' % str(uuid4())[0:4]
        with DaemonContext(pidfile=FileLock(pidfile)):#, stdout=logg, stderr=slogg):
            print "Starting ION CC ... deamon=True, opts=%s" % str(opts)
            main(opts, *args, **kwargs)
    else:
        print "Starting ION CC ... deamon=False, opts=%s" % str(opts)
        main(opts, *args, **kwargs)

if __name__ == '__main__':
    entry()
