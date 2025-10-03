from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views import profile, edit_profile
from .views import  send_password_reset_email
from .views import  send_password_reset_email_by_admin
from .views import add_user


urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.user_login, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    path('assessments/', views.assessments_list, name='assessments_list'),
    path('assessment/<int:assessment_id>/', views.take_assessment, name='take_assessment'),
    path('assessment/<int:assessment_id>/submit/', views.submit_assessment, name='submit_assessment'),
    path('assessment/<int:assessment_id>/result/', views.assessment_result, name='assessment_result'),
    
    path('tutorials/', views.tutorials, name='tutorials'),
    path('upload/', views.upload_assessment, name='upload_assessment'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),

    path('profile/', views.profile, name='profile'),
    path('profile/edit/', edit_profile, name='edit_profile'),
    path('upload-profile-picture/', views.upload_profile_picture, name='upload_profile_picture'),



     # path('reset-password/', CustomPasswordResetView.as_view(), name='custompassword_reset_confirm'),  # your custom reset form
    path('send-reset-email/', send_password_reset_email, name='send_password_reset_email'),

    # Default Django password reset views for confirmation, done, and complete
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='assessment/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.custom_reset_password_view, name='custompassword_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='assessment/password_reset_complete.html'), name='password_reset_complete'),

    path('reset-password/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password/<uidb64>/<token>/', views.custom_reset_password_view, name='custom_reset_password'),
 
    path('users/',views.all_profiles,name='users'),
    path('edit-profile/<int:user_id>/', views.admin_edit_profile, name='admin_edit_profile'),
    path('custom-admin/reset-password/', send_password_reset_email_by_admin, name='admin_reset_password'),

    path('custom-admin/add-user/', views.add_user, name='admin_add_user'),
    path('all-profiles/', views.all_profiles, name='all_profiles')

]