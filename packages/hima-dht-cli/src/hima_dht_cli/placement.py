"""Where a thing runs, shared by the service and game deployment axes."""

from enum import Enum


class Placement(str, Enum):
    """Where a thing runs: host processes or compose services.

    One type serves both axes that ask this question, never one option:
    `hima up` answers it for the managed services, `hima run` answers it
    for the game, and neither reads the other's answer.
    """

    HOST = "host"
    CONTAINER = "container"
