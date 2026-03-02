# sync/tasks.py
from celery import shared_task
from django.utils import timezone
from .models import SyncConfig
from .sync_service import SyncService
import logging

logger = logging.getLogger(__name__)


@shared_task
def auto_sync_all_hospitals():
    """Synchroniser automatiquement tous les hôpitaux"""
    configs = SyncConfig.objects.filter(is_active=True, auto_sync=True)
    
    results = []
    for config in configs:
        try:
            result = auto_sync_hospital.delay(config.hospital_id)
            results.append({'hospital_id': config.hospital_id, 'task_id': result.id})
        except Exception as e:
            logger.error(f"Erreur auto-sync hospital {config.hospital_id}: {e}")
    
    return results


@shared_task
def auto_sync_hospital(hospital_id):
    """Synchroniser un hôpital spécifique"""
    try:
        config = SyncConfig.objects.get(hospital_id=hospital_id)
        
        if config.last_sync_upload:
            elapsed = (timezone.now() - config.last_sync_upload).total_seconds()
            if elapsed < config.sync_interval:
                return {'skipped': True}
        
        sync_service = SyncService(hospital_id)
        upload_results = sync_service.upload_changes(force=False)
        download_results = sync_service.download_changes(force=False)
        
        return {
            'hospital_id': hospital_id,
            'upload': upload_results,
            'download': download_results,
            'timestamp': timezone.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Erreur auto_sync_hospital {hospital_id}: {e}")
        raise