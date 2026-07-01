"""Request helpers.

Inertia's `useForm().post()` sends the payload as application/json (not form-encoded),
so `request.POST` is empty. `get_data` returns whichever is populated, as a dict-like
object exposing `.get()`.
"""
import json


def get_data(request):
    if request.POST:
        return request.POST
    ctype = request.content_type or ""
    if "application/json" in ctype and request.body:
        try:
            return json.loads(request.body)
        except ValueError:
            return {}
    return {}
