from acme.commands.base import Command

MODAL = Command(name="MODAL", routine="run_modal")


def modal():
    return MODAL
