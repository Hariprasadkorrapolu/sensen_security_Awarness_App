from django.contrib import admin
from .models import Assessment, Question, UserAssessmentAttempt, UserAnswer, Tutorial
from .models import Profile


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'total_questions', 'pass_score', 'time_limit', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'description')

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('assessment', 'question_text', 'question_type', 'order')
    list_filter = ('question_type', 'assessment')
    search_fields = ('question_text',)
    ordering = ('assessment', 'order')

@admin.register(UserAssessmentAttempt)
class UserAssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = ('user', 'assessment', 'score', 'is_passed', 'is_completed', 'completed_at')
    list_filter = ('is_passed', 'is_completed', 'assessment')
    search_fields = ('user__username', 'assessment__title')

@admin.register(Tutorial)
class TutorialAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('title', 'description')

@admin.register(Profile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'email', 'phone_number', 'gender', 'address')
    search_fields = ('user__username', 'user__email')

    @admin.display(ordering='user__email', description='Email')
    def email(self, obj):
        return obj.user.email
