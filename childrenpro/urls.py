from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),  # Django admin
    path('', include(('eventapp.urls', 'eventapp'), namespace='eventapp')),

]

if settings.DEBUG:
    urlpatterns += static('media/', document_root=settings.MEDIA_ROOT)
