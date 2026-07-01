from django.urls import path

from . import views

urlpatterns = [
    path("connections", views.connections_index, name="connections"),
    path("connections/save", views.connections_save, name="connections_save"),
    path("connections/<int:conn_id>/delete", views.connections_delete, name="connections_delete"),
    path("connections/<int:conn_id>/set-default", views.connections_set_default, name="connections_set_default"),
    path("connections/<int:conn_id>/test", views.connections_test, name="connections_test"),
]
