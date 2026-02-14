from session import TrailCamSession

class CommandError(RuntimeError):
    pass

class Command:
    session: TrailCamSession
    pass