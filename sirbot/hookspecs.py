"""
Hookspecs of the core plugins
"""

import pluggy

hookspec = pluggy.HookspecMarker('sirbot')


@hookspec
def dispatchers(loop):
    pass


@hookspec
def clients(loop, queue):
    pass