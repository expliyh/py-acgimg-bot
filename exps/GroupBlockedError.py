class GroupBlockedError(Exception):
    """
    This class is a custom exception that is raised when a group is blocked.

    Attributes:
        message (str): The error message to be displayed when the exception is raised.
    """

    def __init__(self, message="Group is blocked"):
        """
        The constructor for the GroupBlockedError class.

        Parameters:
            message (str): The error message to be displayed when the exception is raised.
                           Default is "Group is blocked".
        """
        self.message = message
        super().__init__(self.message)