from collections.abc import Mapping

from rest_framework.views import exception_handler as drf_exception_handler


def first_message(data):
    if isinstance(data, str):  # DRF's ErrorDetail is a str
        return data
    for v in data.values() if isinstance(data, Mapping) else data if isinstance(data, list) else []:
        if msg := first_message(v):
            return msg
    return None


def exception_handler(exc, context):
    """Every API error is an object carrying `message`, the one line the shop shows the buyer."""
    response = drf_exception_handler(exc, context)
    if response is not None:
        if not isinstance(response.data, Mapping):  # ValidationError("...") comes out as a bare list
            response.data = {"non_field_errors": response.data}
        response.data["message"] = first_message(response.data)
    return response
