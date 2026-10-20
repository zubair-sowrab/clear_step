from django.db import models

class BrainDump(models.Model):
    audio_file = models.FileField(upload_to='audio/', blank=True, null=True)
    raw_text = models.TextField(blank=True, null=True)
    target_language = models.CharField(max_length=50, default='en')
    energy_level = models.CharField(max_length=50, default='medium')
    created_at = models.DateTimeField(auto_now_add=True)

class Task(models.Model):
    brain_dump = models.ForeignKey(BrainDump, on_delete=models.CASCADE)
    core_mission = models.CharField(max_length=255, default="Mission")
    friction_rating = models.CharField(max_length=50, default="Medium")
    estimated_minutes = models.IntegerField(default=15)
    micro_steps = models.JSONField(default=list)
    side_quests = models.JSONField(default=list)
    status = models.CharField(max_length=50, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)