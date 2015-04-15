class ConfigValidationError(Exception):
    pass


class ActionValidationError(ConfigValidationError):
    pass
