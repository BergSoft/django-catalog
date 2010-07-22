from grandma.make import BaseMake
from grandma.models import GrandmaSettings
from catalog.grandma_setup.models import CatalogSettings

class Make(BaseMake):
    def make(self):
        super(Make, self).make()
        catalog_settings = CatalogSettings.objects.get_settings()
        grandma_settings = GrandmaSettings.objects.get_settings()
        grandma_settings.render_to('settings.py', 'catalog/grandma/settings.py', {
            'catalog_settings': catalog_settings,
        })
        grandma_settings.render_to('urls.py', 'catalog/grandma/urls.py', {
            'catalog_settings': catalog_settings,
        })