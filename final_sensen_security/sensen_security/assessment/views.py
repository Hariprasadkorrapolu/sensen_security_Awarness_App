import json
import csv
import io
import random
import string
import logging
import pandas as pd
from io import StringIO
from django.conf import settings
from django.urls import reverse
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
import plotly.graph_objects as go
import plotly.express as px
from plotly.offline import plot
from .models import Assessment, Question, UserAssessmentAttempt, UserAnswer, Tutorial, Profile, AdminProfile
from .forms import CustomLoginForm, CustomPasswordChangeForm


UserAssessmentAttempt.completed_at=timezone.now()


def home(request):
    if not request.user.is_authenticated:
        return render(request, 'assessment/login.html')
     # Check if user is staff or superuser - redirect to admin dashboard
    if request.user.is_staff or request.user.is_superuser:
        return redirect('admin_dashboard')
    
    # Check if user is active - only active users can access home
    if not request.user.is_active:
        messages.error(request, 'Your account is inactive. Please contact administrator.')
        return redirect('user_login')
    
    
    # User progress
    user_attempts = UserAssessmentAttempt.objects.filter(user=request.user)
    completed_assessments = user_attempts.filter(is_completed=True).count()
    total_assessments = Assessment.objects.filter(is_active=True).count()
    
    # Progress calculation
    progress_percentage = (completed_assessments / total_assessments * 100) if total_assessments > 0 else 0
    
    # Leaderboard
    leaderboard = UserAssessmentAttempt.objects.filter(is_completed=True)\
        .values('user__username', 'user__first_name', 'user__last_name')\
        .annotate(avg_score=Avg('score'), total_completed=Count('id'))\
        .order_by('-avg_score', '-total_completed')[:10]
    
    # Recent attempts
    recent_attempts = user_attempts.filter(is_completed=True).order_by('-completed_at')[:5]
    
    context = {
        'user': request.user,
        'completed_assessments': completed_assessments,
        'total_assessments': total_assessments,
        'progress_percentage': round(progress_percentage, 1),
        'leaderboard': leaderboard,
        'recent_attempts': recent_attempts,
    }
    return render(request, 'assessment/home.html', context)

@login_required
def assessments_list(request):
    assessments = Assessment.objects.filter(is_active=True)
    user_attempts = UserAssessmentAttempt.objects.filter(user=request.user)
    
    # Add attempt status to each assessment
    for assessment in assessments:
        try:
            attempt = user_attempts.get(assessment=assessment)
            assessment.user_attempt = attempt
        except UserAssessmentAttempt.DoesNotExist:
            assessment.user_attempt = None
    
    return render(request, 'assessment/assessments_list.html', {'assessments': assessments})

@login_required
def take_assessment(request, assessment_id):
    assessment = get_object_or_404(Assessment, id=assessment_id, is_active=True)
    
    # Get or create user attempt
    attempt, created = UserAssessmentAttempt.objects.get_or_create(
        user=request.user,
        assessment=assessment,
        defaults={
            'total_questions': assessment.total_questions,
        }
    )
    
    if attempt.is_completed and request.GET.get('retake') != '1':
        return redirect('assessment_result', assessment_id=assessment_id)
    
    questions = assessment.questions.all()
    
    context = {
        'assessment': assessment,
        'questions': questions,
        'attempt': attempt,
        'kiosk_mode': request.GET.get('kiosk') == '1',
    }
    return render(request, 'assessment/take_assessment.html', context)

@login_required
@csrf_exempt
def submit_assessment(request, assessment_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    assessment = get_object_or_404(Assessment, id=assessment_id)
    attempt = get_object_or_404(UserAssessmentAttempt, user=request.user, assessment=assessment)
    
    try:
        data = json.loads(request.body)
        answers = data.get('answers', {})
        
        with transaction.atomic():
            # Clear existing answers
            UserAnswer.objects.filter(attempt=attempt).delete()
            
            correct_count = 0
            total_questions = assessment.questions.count()
            
            for question_id, user_answer in answers.items():
                question = Question.objects.get(id=question_id, assessment=assessment)
                is_correct = str(user_answer).strip().lower() == str(question.correct_answer).strip().lower()
                
                UserAnswer.objects.create(
                    attempt=attempt,
                    question=question,
                    user_answer=user_answer,
                    is_correct=is_correct
                )
                
                if is_correct:
                    correct_count += 1
            
            # Update attempt
            score = (correct_count / total_questions * 100) if total_questions > 0 else 0
            attempt.score = round(score)
            attempt.correct_answers = correct_count
            attempt.is_completed = True
            attempt.is_passed = score >= assessment.pass_score
            attempt.completed_at = timezone.now()
            attempt.save()
            
            return JsonResponse({
                'success': True,
                'score': attempt.score,
                'correct_answers': correct_count,
                'total_questions': total_questions,
                'is_passed': attempt.is_passed,
                'redirect_url': f'/assessment/{assessment_id}/result/'
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
def assessment_result(request, assessment_id):
    assessment = get_object_or_404(Assessment, id=assessment_id)
    attempt = get_object_or_404(UserAssessmentAttempt, user=request.user, assessment=assessment)
    
    if not attempt.is_completed:
        return redirect('take_assessment', assessment_id=assessment_id)
    
    # Get detailed answers
    user_answers = UserAnswer.objects.filter(attempt=attempt).select_related('question')
    
    context = {
        'assessment': assessment,
        'attempt': attempt,
        'user_answers': user_answers,
    }
    return render(request, 'assessment/assessment_result.html', context)

@login_required
def tutorials(request):
    tutorials = Tutorial.objects.filter(is_active=True).order_by('-created_at')
    return render(request, 'assessment/tutorials.html', {'tutorials': tutorials})


@staff_member_required
def upload_csv(request):
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, "No CSV file uploaded.")
            return redirect('upload_csv')

        try:
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.reader(decoded_file)
            next(reader, None)  # Skip header row if present

            new_count = 0
            skipped_count = 0

            for row in reader:
                if len(row) < 2:
                    # Skip rows with missing data
                    continue
                name, link = row[0].strip(), row[1].strip()
                if not name or not link:
                    continue

                # Create Tutorial if video_url does not exist
                obj, created = Tutorial.objects.get_or_create(
                    video_url=link,
                    defaults={'title': name, 'video_type': 'youtube'}
                )
                if created:
                    new_count += 1
                else:
                    skipped_count += 1

            if new_count > 0:
                messages.success(request, f"{new_count} new video{'s' if new_count > 1 else ''} uploaded.")
            if skipped_count > 0:
                messages.info(request, f"{skipped_count} duplicate video{'s' if skipped_count > 1 else ''} skipped.")

            return redirect('upload_csv')

        except UnicodeDecodeError:
            messages.error(request, "CSV file must be UTF-8 encoded.")
        except Exception as e:
            messages.error(request, f"Error processing CSV file: {str(e)}")
            return redirect('upload_csv')

    return render(request, 'assessment/upload_csv.html')


@staff_member_required
def upload_assessment(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        csv_type = request.POST.get('csv_type')

        try:
            csv_content = csv_file.read().decode('utf-8')
            csv_reader = csv.DictReader(StringIO(csv_content))
            fieldnames = csv_reader.fieldnames

            if csv_type == 'url':  # YouTube URL CSV upload
                required_columns = ['name', 'link']
                
                if not fieldnames or not all(col in fieldnames for col in required_columns):
                    messages.error(request, f'CSV must contain columns: {", ".join(required_columns)}')
                    return render(request, 'assessment/upload_assessment.html')

                tutorials_created = 0
                tutorials_skipped = 0  # Track duplicates
                
                for row_num, row in enumerate(csv_reader, start=1):
                    if not any(row.values()):
                        continue

                    name = row.get('name', '').strip()
                    link = row.get('link', '').strip()

                    if not name or not link:
                        messages.warning(request, f'Skipping row {row_num}: missing name or link.')
                        continue

                    if 'youtube.com' not in link and 'youtu.be' not in link:
                        messages.warning(request, f'Skipping row {row_num}: not a valid YouTube URL.')
                        continue

                    # Use get_or_create to handle duplicates
                    tutorial, created = Tutorial.objects.get_or_create(
                        video_url=link,  # Check for duplicate URLs
                        defaults={
                            'title': name,
                            'description': f'YouTube tutorial: {name}',
                            'video_type': 'youtube',
                            'category': 'Security Awareness',
                            'is_active': True
                        }
                    )
                    
                    if created:
                        tutorials_created += 1
                    else:
                        tutorials_skipped += 1

                # Provide comprehensive feedback
                if tutorials_created > 0:
                    messages.success(request, f'Successfully uploaded {tutorials_created} new YouTube tutorial(s)!')
                if tutorials_skipped > 0:
                    messages.info(request, f'Skipped {tutorials_skipped} duplicate video(s) that already exist.')
                if tutorials_created == 0 and tutorials_skipped == 0:
                    messages.warning(request, 'No valid YouTube tutorials found in CSV.')

            elif csv_type == 'mp4':  # Local MP4 CSV upload
                required_columns = ['name', 'file_path']
                
                if not fieldnames or not all(col in fieldnames for col in required_columns):
                    messages.error(request, f'CSV must contain columns: {", ".join(required_columns)}')
                    return render(request, 'assessment/upload_assessment.html')

                tutorials_created = 0
                tutorials_skipped = 0
                skipped_files = []
                
                for row_num, row in enumerate(csv_reader, start=1):
                    if not any(row.values()):
                        continue

                    name = row.get('name', '').strip()
                    file_path = row.get('file_path', '').strip()
                    description = row.get('description', '').strip()

                    if not name or not file_path:
                        messages.warning(request, f'Skipping row {row_num}: missing name or file path.')
                        continue

                    # Validate that it's an MP4 file
                    if not file_path.lower().endswith(('.mp4', '.MP4')):
                        messages.warning(request, f'Skipping row {row_num}: file must be an MP4.')
                        skipped_files.append(f"Row {row_num}: {file_path}")
                        continue

                    # Use get_or_create to handle duplicates for local files too
                    tutorial, created = Tutorial.objects.get_or_create(
                        local_file_path=file_path,  # Check for duplicate file paths
                        defaults={
                            'title': name,
                            'description': description or f'Local MP4 tutorial: {name}',
                            'video_type': 'local',
                            'category': 'Security Awareness',
                            'is_active': True
                        }
                    )
                    
                    if created:
                        tutorials_created += 1
                    else:
                        tutorials_skipped += 1

                # Provide comprehensive feedback
                if tutorials_created > 0:
                    messages.success(request, f'Successfully uploaded {tutorials_created} new local MP4 tutorial(s)!')
                if tutorials_skipped > 0:
                    messages.info(request, f'Skipped {tutorials_skipped} duplicate file(s) that already exist.')
                if skipped_files:
                    messages.warning(request, f'Skipped {len(skipped_files)} files due to invalid format or missing files.')

            else:
                messages.error(request, 'Invalid CSV type selected.')
                return render(request, 'assessment/upload_assessment.html')

            return redirect('admin_dashboard')

        except UnicodeDecodeError:
            messages.error(request, 'CSV file must be UTF-8 encoded.')
        except Exception as e:
            messages.error(request, f'Error processing CSV file: {str(e)}')

    return render(request, 'assessment/upload_assessment.html')


def admin_dashboard(request):
    # Basic statistics
    total_users = User.objects.count()
    total_assessments = Assessment.objects.count()
    total_attempts = UserAssessmentAttempt.objects.filter(is_completed=True).count()
    
    # Pass/Fail statistics
    passed_attempts = UserAssessmentAttempt.objects.filter(is_completed=True, is_passed=True).count()
    failed_attempts = total_attempts - passed_attempts
    pass_percentage = (passed_attempts / total_attempts * 100) if total_attempts > 0 else 0
    
    # Assessment results for visualization
    assessment_results = UserAssessmentAttempt.objects.filter(is_completed=True)\
        .select_related('user', 'assessment')\
        .order_by('-completed_at')
    
    # Leaderboard data - Top 10 users by average score
    from django.db.models import Avg, Count
    leaderboard_data = UserAssessmentAttempt.objects.filter(is_completed=True)\
        .values('user__username')\
        .annotate(
            avg_score=Avg('score'),
            total_attempts=Count('id')
        )\
        .filter(total_attempts__gte=1)\
        .order_by('-avg_score')\
        [:15]  # Top 15 users for better scrolling
    
    # Convert to list and add username field
    leaderboard_list = []
    for user_data in leaderboard_data:
        leaderboard_list.append({
            'username': user_data['user__username'],
            'avg_score': user_data['avg_score'],
            'total_attempts': user_data['total_attempts']
        })
    
    # ADD THIS: Assessment Overview Data
    assessment_overview = []
    assessments = Assessment.objects.all()
    
    for assessment in assessments:
        # Get all users
        all_users = User.objects.all()
        
        # Get users who completed this assessment
        completed_attempts = UserAssessmentAttempt.objects.filter(
            assessment=assessment,
            is_completed=True
        ).select_related('user')
        
        # Get completed users with their scores
        completed_users = []
        completed_user_ids = []
        for attempt in completed_attempts:
            completed_users.append({
                'username': attempt.user.username,
                'score': attempt.score
            })
            completed_user_ids.append(attempt.user.id)
        
        # Get pending users (users who haven't completed this assessment)
        pending_users = []
        for user in all_users:
            if user.id not in completed_user_ids:
                pending_users.append({
                    'username': user.username
                })
        
        assessment_overview.append({
            'id': assessment.id,
            'title': assessment.title,
            'description': assessment.description,
            'completed_count': len(completed_users),
            'pending_count': len(pending_users),
            'completed_users': completed_users,
            'pending_users': pending_users
        })
    
    # Initialize chart variables
    score_chart = ""
    performance_chart = ""
    timeline_chart = ""
    
    try:
        if assessment_results.exists():
            # 1. Assessment-wise Pass/Fail Stacked Bar Chart with reduced bar width
            assessment_performance = {}
            for attempt in assessment_results:
                assessment_name = attempt.assessment.title
                if assessment_name not in assessment_performance:
                    assessment_performance[assessment_name] = {'passed': 0, 'failed': 0, 'total': 0}
                
                if attempt.is_passed:
                    assessment_performance[assessment_name]['passed'] += 1
                else:
                    assessment_performance[assessment_name]['failed'] += 1
                assessment_performance[assessment_name]['total'] += 1
            
            if assessment_performance:
                assessment_names = list(assessment_performance.keys())
                passed_counts = [data['passed'] for data in assessment_performance.values()]
                failed_counts = [data['failed'] for data in assessment_performance.values()]
                
                fig_stacked = go.Figure()
                fig_stacked.add_trace(go.Bar(
                    name='Passed',
                    x=assessment_names,
                    y=passed_counts,
                    marker_color='#28a745',
                    width=0.4  # Reduced bar width from default (0.8) to 0.4
                ))
                fig_stacked.add_trace(go.Bar(
                    name='Failed',
                    x=assessment_names,
                    y=failed_counts,
                    marker_color='#dc3545',
                    width=0.4  # Reduced bar width from default (0.8) to 0.4
                ))
                
                fig_stacked.update_layout(
                    title='Assessment Results - Pass/Fail Distribution',
                    xaxis_title='Assessment',
                    yaxis_title='Number of Attempts',
                    barmode='stack',
                    plot_bgcolor='white',
                    paper_bgcolor='white',
                    xaxis_tickangle=-45,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    bargap=0.3  # Add gap between bars for better separation
                )
                score_chart = plot(fig_stacked, output_type='div', include_plotlyjs=False)
            
            # 2. Assessment performance chart (keeping the existing one)
            assessment_performance_avg = {}
            for attempt in assessment_results:
                assessment_name = attempt.assessment.title
                if assessment_name not in assessment_performance_avg:
                    assessment_performance_avg[assessment_name] = {'scores': [], 'attempts': 0}
                assessment_performance_avg[assessment_name]['scores'].append(attempt.score)
                assessment_performance_avg[assessment_name]['attempts'] += 1
            
            if assessment_performance_avg:
                assessment_names = list(assessment_performance_avg.keys())
                avg_scores = [
                    sum(data['scores']) / len(data['scores']) if data['scores'] else 0
                    for data in assessment_performance_avg.values()
                ]
                
                performance_df = pd.DataFrame({
                    'Assessment': assessment_names,
                    'Average Score': avg_scores
                })
                
                fig_performance = px.bar(performance_df, x='Assessment', y='Average Score',
                                         title='Average Score by Assessment')
                fig_performance.update_layout(
                    xaxis_title='Assessment', 
                    yaxis_title='Average Score (%)',
                    xaxis_tickangle=-45,
                    plot_bgcolor='white',
                    paper_bgcolor='white'
                )
                performance_chart = plot(fig_performance, output_type='div', include_plotlyjs=False)
            
            # 3. User Percentage Growth Over Time
            from django.db.models import Count
            from datetime import datetime, timedelta
            
            # Get user registration data over time (last 12 months)
            twelve_months_ago = timezone.now() - timedelta(days=365)
            
            # Group users by month
            user_growth_data = []
            current_date = twelve_months_ago
            total_users_cumulative = 0
            
            while current_date <= timezone.now():
                month_end = current_date.replace(day=28) + timedelta(days=4)
                month_end = month_end - timedelta(days=month_end.day-1) + timedelta(days=32)
                month_end = month_end.replace(day=1) - timedelta(days=1)
                
                users_this_month = User.objects.filter(
                    date_joined__gte=current_date,
                    date_joined__lte=month_end
                ).count()
                
                total_users_cumulative += users_this_month
                
                user_growth_data.append({
                    'month': current_date.strftime('%b %Y'),
                    'new_users': users_this_month,
                    'total_users': total_users_cumulative,
                    'growth_rate': ((users_this_month / total_users_cumulative * 100) if total_users_cumulative > 0 else 0)
                })
                
                # Move to next month
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
            
            if user_growth_data:
                months = [data['month'] for data in user_growth_data]
                total_users_data = [data['total_users'] for data in user_growth_data]
                new_users_data = [data['new_users'] for data in user_growth_data]
                
                fig_growth = go.Figure()
                
                # Add cumulative users line
                fig_growth.add_trace(go.Scatter(
                    x=months,
                    y=total_users_data,
                    mode='lines+markers',
                    name='Total Users',
                    line=dict(color='#007bff', width=3),
                    marker=dict(size=8)
                ))
                
                # Add new users bar
                fig_growth.add_trace(go.Bar(
                    x=months,
                    y=new_users_data,
                    name='New Users',
                    marker_color='#28a745',
                    opacity=0.7,
                    yaxis='y2'
                ))
                
                fig_growth.update_layout(
                    title='User Growth Over Time',
                    xaxis_title='Month',
                    yaxis=dict(title='Total Users', side='left'),
                    yaxis2=dict(title='New Users', side='right', overlaying='y'),
                    plot_bgcolor='white',
                    paper_bgcolor='white',
                    xaxis_tickangle=-45,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                timeline_chart = plot(fig_growth, output_type='div', include_plotlyjs=False)
    
    except Exception as e:
        print(f"Chart generation error: {e}")
        # Continue without charts if there's an error
        pass
    
    context = {
        'total_users': total_users,
        'total_assessments': total_assessments,
        'total_attempts': total_attempts,
        'passed_attempts': passed_attempts,
        'failed_attempts': failed_attempts,
        'pass_percentage': round(pass_percentage, 1),
        'assessment_results': assessment_results[:20],
        'leaderboard_data': leaderboard_list,
        'assessment_overview': assessment_overview,  # ADD THIS LINE
        'score_chart': score_chart,
        'performance_chart': performance_chart,
        'timeline_chart': timeline_chart,
    }
    
    return render(request, 'assessment/admin_dashboard.html', context)


@login_required
def profile(request):
    user = request.user
    profile, created = Profile.objects.get_or_create(user=user)
    return render(request, 'assessment/profile.html', {
        'user': user,
        'profile': profile
    })

from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

@login_required
def upload_profile_picture(request):
    if request.method == 'POST' and request.FILES.get('profile_pic'):
        profile = request.user.profile
        profile.profile_image = request.FILES['profile_pic']
        profile.save()
    return redirect('profile')  


@login_required
def edit_profile(request):
    user = request.user
    profile, created = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        # Update User model fields
        user.username = request.POST.get('username', user.username)
        user.email = request.POST.get('email', user.email)
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.save()

        # Update Profile model fields
        profile.phone_number = request.POST.get('phone')
        profile.gender = request.POST.get('gender')
        profile.address = request.POST.get('address')
        if request.FILES.get('profile_pic'):
            profile.profile_image = request.FILES['profile_pic']
        profile.save()

        messages.success(request, "Profile updated successfully.")
        return redirect('profile')  # or 'profile_view' depending on your URL name

    return render(request, 'assessment/edit_profile_form.html', {'user': user, 'profile': profile})



import difflib
from django.contrib.auth import logout


@login_required
def send_password_reset_email(request):
    if request.method == "POST":
        user = request.user
        email = user.email

        if not email:
            messages.error(request, "No email associated with your account.")
            return redirect('profile')

        # Email matched, proceed with reset
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_link = request.build_absolute_uri(f"/reset/{uid}/{token}/")

        subject = "Password Reset Requested"
        message = render_to_string('assessment/password_reset_email.html', {
            'user': user,
            'reset_link': reset_link,
        })
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [email]

        try:
            send_mail(subject, message, from_email, recipient_list, fail_silently=False)
            messages.success(request, f"Password reset link has been sent to {email}. You have been logged out for security reasons.")
            logout(request)  # Log out the user immediately after sending the email
        except Exception as e:
            messages.error(request, f"Error sending email: {str(e)}")

        return redirect('profile')

from django.core.mail import send_mail

@login_required
def send_email_view(request):
    user_email = request.user.email  # current logged-in user's email
    
    send_mail(
        subject="Subject here",
        message="Your message here",
        from_email=user_email,          # <-- dynamic from email
        recipient_list=["recipient@example.com"],
        fail_silently=False,
    )
    # rest of your view code


from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

def user_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        try:
            user_obj = User.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
        except User.DoesNotExist:
            user = None

        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, 'Invalid credentials')

    return render(request, 'assessment/login.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home.html')  # 👈 change this to your actual home/profile URL name
        else:
            return render(request, 'login.html', {'form': form, 'error': 'Invalid credentials'})
    else:
        form = AuthenticationForm()
    return render(request, 'assessment/login.html', {'form': form})
from django import forms


def forgot_password_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_link = request.build_absolute_uri(f'/reset-password/{uid}/{token}/')

            # Send email
            send_mail(
                subject='Reset Your Password',
                message=f'Click the link to reset your password:\n{reset_link}',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False
            )

            messages.success(request, 'Password reset link has been sent to your email.')
            return redirect('login')

        except User.DoesNotExist:
            messages.error(request, 'No account with that email exists.')
            return redirect('forgot_password')

    return render(request, 'assessment/forgot_password.html')

def custom_reset_password_view(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)

        if not default_token_generator.check_token(user, token):
            messages.error(request, 'The reset link is invalid or expired.')
            return redirect('forgot_password')

    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        messages.error(request, 'Invalid reset link.')
        return redirect('forgot_password')

    if request.method == 'POST':
        new_password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if new_password == confirm_password:
            user.set_password(new_password)
            user.save()
            messages.success(request, 'Password reset successful. You can log in now.')
            return redirect('login')  # 🔍 This depends on your URL name
        else:
            messages.error(request, 'Passwords do not match.')

    return render(request, 'assessment/reset_password_form.html')

import re
from django.core.exceptions import ValidationError

def validate_password_strength(password):
    """Validate password strength:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValidationError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValidationError("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        raise ValidationError("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        raise ValidationError("Password must contain at least one special character.")

def custom_reset_password_view(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)

        if not default_token_generator.check_token(user, token):
            messages.error(request, 'The reset link is invalid or expired.')
            return redirect('forgot_password')

    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        messages.error(request, 'Invalid reset link.')
        return redirect('forgot_password')

    if request.method == 'POST':
        new_password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        else:
            try:
                validate_password_strength(new_password)
                user.set_password(new_password)
                user.save()
                messages.success(request, 'Password reset successful. You can log in now.')
                return redirect('login')  # Adjust this according to your URL name
            except ValidationError as e:
                messages.error(request, e.message)

    return render(request, 'assessment/reset_password_form.html')

@login_required
def all_profiles(request):
    profiles = Profile.objects.select_related('user').all()
    return render(request, 'assessment/users.html', {'profiles': profiles})

def is_admin(user):
    return user.is_staff  # or user.is_superuser depending on your setup

@login_required
def admin_edit_profile(request, user_id):
    user = get_object_or_404(User, id=user_id)
    profile = get_object_or_404(Profile, user=user)

    if request.method == 'POST':
        user.email = request.POST.get('email')
        user.first_name = request.POST.get('first_name')
        user.last_name = request.POST.get('last_name')
        profile.phone_number = request.POST.get('phone_number')

        if 'profile_image' in request.FILES:
            profile.profile_image = request.FILES['profile_image']

        user.save()
        profile.save()

        return redirect('users')  # Redirect to the user list page

    return redirect('users')  # Not expected to render a page, just redirect


logger = logging.getLogger(__name__)

def send_password_reset_email_by_admin(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            user = User.objects.get(email=email)

            # Generate random 8-character passw ord
            new_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            user.set_password(new_password)
            user.save()

            # Send email
            send_mail(               

    subject="New Login Credentials",
    message=f"""Hello {user.first_name} {user.last_name},

Your password has been successfully reset. You can now log in with the following temporary password:

 New Password: {new_password}

We recommend changing this password after logging in.

Regards,  
Your Admin Team
""",
    from_email="keerthanaperavali9@example.com",
    recipient_list=[user.email],
    fail_silently=False,
)

            logger.info(f"Password reset email sent to {user.email}")
            return JsonResponse({'status': 'success', 'message': f'Reset password sent to {user.email}'})
        except User.DoesNotExist:
            logger.warning("User with this email does not exist.")
            return JsonResponse({'status': 'error', 'message': 'User not found'})
        except Exception as e:
            logger.error(f"Error sending reset password: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'Internal server error: {str(e)}'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


from django.views.decorators.http import require_GET, require_POST

def add_user(request):
    if request.method == "POST":
        email = request.POST.get('email')
        emp_id = request.POST.get('emp_id')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')

        # 1. Check required fields
        if not email or not emp_id:
            messages.error(request, "Email and Emp ID are required.")
            return redirect('all_profiles')

        # 2. Check for duplicate email
        if User.objects.filter(email=email).exists():
            messages.error(request, "User with this email already exists.")
            return redirect('all_profiles')

        # 3. Check for duplicate emp_id
        if Profile.objects.filter(emp_id=emp_id).exists():
              return JsonResponse({'message': 'Emp ID already exists.'}, status=400)

        try:
            # 4. Create the user
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=User.objects.make_random_password()
            )

            # 5. Assign emp_id to the profile (created via signal)
            profile, created = Profile.objects.get_or_create(user=user)
            profile.emp_id = emp_id
            profile.user_code = "SS-123"  # You can auto-generate this if needed
            profile.save()

            messages.success(request, "User added successfully!")
            return redirect('all_profiles')

        except Exception as e:
            print("Server Error:", e)
            messages.error(request, "Server error occurred while creating user.")
            return redirect('all_profiles')

    return render(request, 'add_user.html')