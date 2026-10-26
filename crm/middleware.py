from django.conf import settings

from .locale_data import CURRENCIES, current_currency


class CurrencyMiddleware:
    """Makes the user's chosen display currency available to money filters for this request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        currency = request.session.get("currency") if hasattr(request, "session") else None
        if currency not in CURRENCIES:
            currency = settings.DEFAULT_CURRENCY
        token = current_currency.set(currency)
        try:
            return self.get_response(request)
        finally:
            current_currency.reset(token)
