from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('upload/', views.upload_audio, name='upload_audio'),
    path('unstick/', views.unstick_step, name='unstick_step'),
    path('handoff/', views.generate_handoff, name='generate_handoff'),
    path('history/', views.get_history, name='get_history'),
]