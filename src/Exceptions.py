

class RepositoryError(Exception):
    """Provide an exception to allow us to bail out cleanly

    Use this when there is an unrecoverable error.

    Attributes:
    description -- string describing the error
    http_code  -- integer containing the http response code that covers the nature of the error
    """
    def __init__(self, description = 'Internal Repository Error', http_code = 500):
        self._description = description
        self._code = http_code

    def description(self):
        return self._description

    def code(self):
        return self._code

    def http_error(self):
        return self._description, self._code



class RepositoryFailure(Exception):
    """Provide an exception to allow us to propagate failures up

    Use this when there is a failure that prevents a task completing

    Attributes:
    description -- string describing the failure
    http_code  -- integer containing the http response code that covers the nature of the failure
    """
    def __init__(self, description = 'Repository Request Failed', http_code = 501):
        self._description = description
        self._code = http_code

    def description(self):
        return self._description

    def code(self):
        return self._code

    def http_error(self):
        return self._description, self._code

