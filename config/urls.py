"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Hybrid Search admin"
admin.site.site_title = "Hybrid Search admin"
admin.site.index_title = "Crawl jobs, pages and queries"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("search.urls")),
]
