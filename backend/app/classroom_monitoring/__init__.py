"""Automatic Google Classroom submission monitoring.

Monitoring detects turned-in work, retrieves and inspects the attachments, and
only then hands an eligible submission to the existing correction queue.  It
never calls a marking provider: inspection is deterministic and local, and the
existing worker performs every correction.
"""
