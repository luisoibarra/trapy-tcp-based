CON_ALREADY_CLOSED_MSG = "Connection already closed"
CON_CLOSE_READ_MSG = "Cannot read from a closed conenction"
ACCEPT_IN_NON_SERVER_MSG = "Can't listen in a non server connection"

class ConnException(Exception):
    """
    Base Connection Exception
    """
    pass
