from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver
import os
from django.db import IntegrityError

# =========================
# Assessment & Questions
# =========================

class Assessment(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    time_limit = models.IntegerField(default=30, help_text="Time limit per question in seconds")
    pass_score = models.IntegerField(default=70, validators=[MinValueValidator(0), MaxValueValidator(100)])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    @property
    def total_questions(self):
        return self.questions.count()


class Question(models.Model):
    QUESTION_TYPES = [
        ('multiple_choice', 'Multiple Choice'),
        ('true_false', 'True/False'),
    ]

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='multiple_choice')
    options = models.JSONField(default=list, help_text="List of options for multiple choice questions")
    correct_answer = models.CharField(max_length=200)
    explanation = models.TextField(blank=True, null=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.assessment.title} - Q{self.order}"


# =========================
# User Attempts & Answers
# =========================

class UserAssessmentAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)
    correct_answers = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    is_passed = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['user', 'assessment']

    def __str__(self):
        return f"{self.user.username} - {self.assessment.title} - {self.score}%"


class UserAnswer(models.Model):
    attempt = models.ForeignKey(UserAssessmentAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    user_answer = models.CharField(max_length=200)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.attempt.user.username} - Q{self.question.order}"


# =========================
# Tutorials
# =========================

class Tutorial(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    video_url = models.URLField(help_text="YouTube or other video URL")
    thumbnail = models.ImageField(upload_to='tutorials/', blank=True, null=True)
    category = models.CharField(max_length=100, default='Security Awareness')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    @property
    def get_video_source(self):
        """Return the appropriate video source based on type"""
        if hasattr(self, 'video_type'):
            if self.video_type == 'youtube' and self.video_url:
                return self.video_url
            elif self.video_type == 'local':
                if hasattr(self, 'video_file') and self.video_file:
                    return self.video_file.url
                elif hasattr(self, 'local_file_path') and self.local_file_path:
                    return f"/media/local_videos/{os.path.basename(self.local_file_path)}"
        return None

    @property
    def is_file_accessible(self):
        """Check if local file exists (for CSV uploaded files)"""
        if hasattr(self, 'video_type') and self.video_type == 'local':
            if hasattr(self, 'local_file_path') and self.local_file_path:
                return os.path.exists(self.local_file_path)
        return True


# =========================
# Profile & Admin Profile
# =========================

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    profile_image = models.ImageField(upload_to='profiles/', blank=True, null=True)
    phone_number = models.CharField(max_length=10, blank=True)
    gender = models.CharField(max_length=10, choices=[('Male', 'Male'), ('Female', 'Female')], blank=True)
    address = models.TextField(blank=True)
    emp_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    user_code = models.CharField(max_length=100, unique=True)


    def __str__(self):
        return self.user.username


class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


# =========================
# Signal for Profile Auto-Creation
# =========================
@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    if created:
        count = Profile.objects.count() + 1
        emp_id = f"EMP{count:03}"

        # Ensure uniqueness
        while Profile.objects.filter(emp_id=emp_id).exists():
            count += 1
            emp_id = f"EMP{count:03}"

        try:
            Profile.objects.create(
                user=instance,
                emp_id=emp_id,
                user_code=f"SS-{count:03}"
            )
        except IntegrityError as e:
            print("IntegrityError during profile creation:", e)
    else:
        # Avoid saving if profile doesn't exist
        if hasattr(instance, 'profile'):
            instance.profile.save()