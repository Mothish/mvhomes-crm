from django.apps import AppConfig


class CrmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "crm"
    verbose_name = "Lead CRM"

    def ready(self):
        from django.conf import settings
        from django.contrib.auth.signals import user_logged_in

        def reset_currency(sender, request, user, **kwargs):
            request.session["currency"] = settings.DEFAULT_CURRENCY

        user_logged_in.connect(reset_currency, weak=False, dispatch_uid="crm_reset_currency")
