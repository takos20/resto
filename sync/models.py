# sync/models.py
from django.db import models
from hospital.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

from hospital.models import Hospital

class SyncLog(models.Model):
    """Log de synchronisation pour tracer les opérations"""
    
    SYNC_STATUS = [
        ('PENDING', 'En attente'),
        ('SUCCESS', 'Réussi'),
        ('FAILED', 'Échoué'),
        ('CONFLICT', 'Conflit'),
    ]
    
    SYNC_DIRECTION = [
        ('UPLOAD', 'Local → Online'),
        ('DOWNLOAD', 'Online → Local'),
    ]
    
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, null=True)
    direction = models.CharField(max_length=20, choices=SYNC_DIRECTION)
    status = models.CharField(max_length=20, choices=SYNC_STATUS, default='PENDING')
    
    # Generic relation pour n'importe quel modèle
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Métadonnées
    operation = models.CharField(max_length=20)  # CREATE, UPDATE, DELETE
    data_snapshot = models.JSONField(null=True)  # Copie des données
    error_message = models.TextField(null=True, blank=True)
    
    # Timestamps
    createdAt = models.DateTimeField(auto_now_add=True)
    syncedAt = models.DateTimeField(null=True, blank=True)
    
    # Tracking
    local_updatedAt = models.DateTimeField()
    remote_updatedAt = models.DateTimeField(null=True, blank=True)
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        db_table = 'sync_log'
        ordering = ['-createdAt']
        indexes = [
            models.Index(fields=['hospital', 'status']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['createdAt']),
        ]


class SyncConfig(models.Model):
    """Configuration de synchronisation par hôpital"""
    
    hospital = models.OneToOneField(Hospital, on_delete=models.CASCADE, null=True)
    
    # URLs
    remote_api_url = models.URLField()
    local_api_url = models.URLField(null=True, blank=True)
    
    # Authentification
    api_token = models.CharField(max_length=500)
    
    # Options de sync
    auto_sync = models.BooleanField(default=False)
    sync_interval = models.IntegerField(default=300)  # secondes
    
    # Modèles à synchroniser
    models_to_sync = models.JSONField(default=list)  # ['Patient', 'Bills', ...]
    
    # Dernière synchronisation
    last_sync_upload = models.DateTimeField(null=True, blank=True)
    last_sync_download = models.DateTimeField(null=True, blank=True)
    
    # Stratégie de conflit
    conflict_strategy = models.CharField(
        max_length=20,
        choices=[
            ('LOCAL_WINS', 'Local gagne'),
            ('REMOTE_WINS', 'Remote gagne'),
            ('MANUAL', 'Résolution manuelle'),
        ],
        default='MANUAL'
    )
    
    is_active = models.BooleanField(default=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sync_config'