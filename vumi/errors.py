class VumiError(Exception):
    pass


class InvalidMessage(VumiError):
    pass


class InvalidMessageType(VumiError):
    pass


class MissingMessageField(InvalidMessage):
    pass


class InvalidMessageField(InvalidMessage):
    pass


class DuplicateConnectorError(VumiError):
    pass


class InvalidEndpoint(VumiError):
    """Raised when attempting to send a message to an invalid endpoint."""


# Re-export this for compatibility.
from confmodel.errors import ConfigError

ConfigError
