from django.apps import AppConfig


class WasteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waste"
    verbose_name = "Solid Waste Management"

    def ready(self):
        import waste.signals  # noqa: F401
