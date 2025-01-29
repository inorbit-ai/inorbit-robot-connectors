# SPDX-FileCopyrightText: 2024 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT
"""
observable

Simple implementation of the Observer pattern.

Classes:
    Observable: Simple implementation of the Observer pattern.
"""


class Observable:
    """
    Simple implementation of the Observer pattern. Objects that can be observed must subclass from
    this class.

    They call `self.notify_observers()` with any number of (positional and named) arguments to
    propagate events.

    Observers must implement a notify(), which receives first the caller (observed) object as
    argument, then all the arguments passed to notify_observers. There is no class implemented
    for "Observers" themselves, they simply need to implement this notify() method.
    """

    def __init__(self):
        self._observers = []

    def subscribe(self, observer):
        self._observers.append(observer)

    def unsubscribe(self, observer):
        self._observers.remove(observer)

    async def notify_observers(self, *args, **kwargs):
        for obs in self._observers:
            await obs.notify(self, *args, **kwargs)
