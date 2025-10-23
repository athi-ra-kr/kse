from django.urls import path
from . import views

app_name = "eventapp"   # <-- important so {% url 'eventapp:...' %} works

urlpatterns = [
    path("", views.index, name="index"),
    path("adminlogin/", views.adminlogin_view, name="adminlogin"),
    path("logout/", views.logout_view, name="logout"),

    path("apply/", views.apply, name="apply"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("applications/<int:pk>/edit/", views.application_edit, name="application_edit"),
    path("applications/<int:pk>/delete/", views.application_delete, name="application_delete"),

    # schools
    path("schools/", views.school_list, name="school_list"),
    path("schools/create/", views.school_create, name="school_create"),
    path("schools/<int:pk>/update/", views.school_update, name="school_update"),
    path("schools/<int:pk>/delete/", views.school_delete, name="school_delete"),
    path("schools/bulk-add/", views.school_bulk_add, name="school_bulk_add"),

    # programmes
    path("programmes/", views.program_list, name="program_list"),
    path("programmes/create/", views.program_create, name="program_create"),
    path("programmes/<int:pk>/update/", views.program_update, name="program_update"),
    path("programmes/<int:pk>/delete/", views.program_delete, name="program_delete"),
    path("programmes/<int:pk>/edit/", views.program_edit_page, name="program_edit_page"),

    # banners
    path("banners/", views.banner_list, name="banner_list"),
    path("banners/create/", views.banner_create, name="banner_create"),
    path("banners/<int:pk>/update/", views.banner_update, name="banner_update"),
    path("banners/<int:pk>/delete/", views.banner_delete, name="banner_delete"),

    path("winners/", views.winners, name="winners"),
    path("winners/export/", views.winners_export, name="winners_export"),
    path("winners/create/", views.winners_create, name="winners_create"),
    path("winners/<int:pk>/update/", views.winners_update, name="winners_update"),
    path("winners/<int:pk>/delete/", views.winners_delete, name="winners_delete"),

    # ✅ Excel export
    path("dashboard/export/", views.export_applications_csv, name="export_applications_csv"),
    path("winnerslist/", views.winnerslist, name="winnerslist"),

]
