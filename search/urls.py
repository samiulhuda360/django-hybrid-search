from django.urls import path

from . import views

app_name = "search"

urlpatterns = [
    path("", views.home, name="home"),
    path("search", views.results, name="results"),
    path("about", views.about, name="about"),
    path("api/search", views.api_search, name="api_search"),
    path("api/suggest", views.api_suggest, name="api_suggest"),
    path("api/answer", views.api_answer, name="api_answer"),
]
