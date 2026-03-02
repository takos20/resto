# sync/services/sync_service.py
import requests
import logging
from django.db import transaction
from django.apps import apps
from django.utils import timezone
from datetime import datetime, timedelta
from .models import SyncLog, SyncConfig

logger = logging.getLogger(__name__)


class SyncService:
    """Service de synchronisation bidirectionnelle"""
    
    def __init__(self, hospital_id):
        self.hospital_id = hospital_id
        self.config = SyncConfig.objects.get(hospital_id=hospital_id)
        self.session = self._create_session()
    
    def _create_session(self):
        """Créer une session HTTP avec authentification"""
        session = requests.Session()
        session.headers.update({
            'Authorization': f'Bearer {self.config.api_token}',
            'Content-Type': 'application/json'
        })
        return session
    
    # ==================== UPLOAD (Local → Remote) ====================
    
    def upload_changes(self, force=False):
        """
        Envoyer les modifications locales vers le serveur distant
        
        Args:
            force: Forcer la sync même si auto_sync est désactivé
        """
        if not self.config.is_active:
            logger.warning(f"Sync désactivée pour hospital {self.hospital_id}")
            return
        
        if not self.config.auto_sync and not force:
            logger.info("Auto-sync désactivé")
            return
        
        results = {
            'success': 0,
            'failed': 0,
            'conflicts': 0,
            'skipped': 0
        }
        
        try:
            # Pour chaque modèle à synchroniser
            for model_name in self.config.models_to_sync:
                try:
                    model_results = self._upload_model(model_name)
                    results['success'] += model_results['success']
                    results['failed'] += model_results['failed']
                    results['conflicts'] += model_results['conflicts']
                    results['skipped'] += model_results['skipped']
                except Exception as e:
                    logger.error(f"Erreur upload {model_name}: {e}")
                    results['failed'] += 1
            
            # Mettre à jour le timestamp
            self.config.last_sync_upload = timezone.now()
            self.config.save()
            
            logger.info(f"Upload terminé: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Erreur upload_changes: {e}")
            raise
    
    def _upload_model(self, model_name):
        """Uploader les changements d'un modèle spécifique"""
        results = {'success': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        try:
            Model = apps.get_model('your_app', model_name)
        except LookupError:
            logger.error(f"Modèle {model_name} introuvable")
            return results
        
        # Récupérer les objets modifiés depuis la dernière sync
        last_sync = self.config.last_sync_upload or timezone.now() - timedelta(days=365)
        
        # Objets à synchroniser
        queryset = Model.objects.filter(
            hospital_id=self.hospital_id,
            updatedAt__gt=last_sync,
            deleted=False
        )
        
        # Si le modèle a is_shared, ne sync que is_shared=True
        if hasattr(Model, 'is_shared'):
            queryset = queryset.filter(is_shared=True)
        
        for obj in queryset:
            try:
                result = self._upload_object(obj, model_name)
                results[result] += 1
            except Exception as e:
                logger.error(f"Erreur upload {model_name} #{obj.id}: {e}")
                results['failed'] += 1
        
        return results
    
    def _upload_object(self, obj, model_name):
        """Uploader un objet individuel"""
        
        # Vérifier s'il existe déjà un log en attente
        existing_log = SyncLog.objects.filter(
            hospital_id=self.hospital_id,
            content_type__model=model_name.lower(),
            object_id=obj.id,
            status='PENDING',
            direction='UPLOAD'
        ).first()
        
        if existing_log:
            return 'skipped'
        
        # Créer un log
        sync_log = SyncLog.objects.create(
            hospital_id=self.hospital_id,
            direction='UPLOAD',
            status='PENDING',
            content_object=obj,
            operation='UPDATE' if hasattr(obj, 'pk') and obj.pk else 'CREATE',
            data_snapshot=self._serialize_object(obj),
            local_updated_at=obj.updatedAt if hasattr(obj, 'updatedAt') else timezone.now()
        )
        
        try:
            # Préparer les données
            data = self._serialize_object(obj)
            data['hospital_id'] = self.hospital_id
            
            # Envoyer au serveur distant
            url = f"{self.config.remote_api_url}/sync/{model_name.lower()}/"
            
            if hasattr(obj, 'code') and obj.code:
                # Tentative de UPDATE
                response = self.session.put(f"{url}{obj.code}/", json=data)
                if response.status_code == 404:
                    # Créer si n'existe pas
                    response = self.session.post(url, json=data)
            else:
                # CREATE
                response = self.session.post(url, json=data)
            
            if response.status_code in [200, 201]:
                sync_log.status = 'SUCCESS'
                sync_log.synced_at = timezone.now()
                sync_log.remote_updated_at = timezone.now()
                sync_log.save()
                return 'success'
            
            elif response.status_code == 409:  # Conflit
                sync_log.status = 'CONFLICT'
                sync_log.error_message = response.json().get('message', 'Conflit détecté')
                sync_log.save()
                
                # Résolution automatique si configuré
                if self.config.conflict_strategy != 'MANUAL':
                    self._resolve_conflict(sync_log, response.json())
                    return 'success'
                
                return 'conflict'
            
            else:
                sync_log.status = 'FAILED'
                sync_log.error_message = f"HTTP {response.status_code}: {response.text}"
                sync_log.save()
                return 'failed'
        
        except Exception as e:
            sync_log.status = 'FAILED'
            sync_log.error_message = str(e)
            sync_log.save()
            return 'failed'
    
    # ==================== DOWNLOAD (Remote → Local) ====================
    
    def download_changes(self, force=False):
        """
        Télécharger les modifications du serveur distant
        
        Args:
            force: Forcer la sync même si auto_sync est désactivé
        """
        if not self.config.is_active:
            logger.warning(f"Sync désactivée pour hospital {self.hospital_id}")
            return
        
        if not self.config.auto_sync and not force:
            logger.info("Auto-sync désactivé")
            return
        
        results = {
            'success': 0,
            'failed': 0,
            'conflicts': 0,
            'skipped': 0
        }
        
        try:
            # Pour chaque modèle à synchroniser
            for model_name in self.config.models_to_sync:
                try:
                    model_results = self._download_model(model_name)
                    results['success'] += model_results['success']
                    results['failed'] += model_results['failed']
                    results['conflicts'] += model_results['conflicts']
                    results['skipped'] += model_results['skipped']
                except Exception as e:
                    logger.error(f"Erreur download {model_name}: {e}")
                    results['failed'] += 1
            
            # Mettre à jour le timestamp
            self.config.last_sync_download = timezone.now()
            self.config.save()
            
            logger.info(f"Download terminé: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Erreur download_changes: {e}")
            raise
    
    def _download_model(self, model_name):
        """Télécharger les changements d'un modèle spécifique"""
        results = {'success': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}
        
        try:
            Model = apps.get_model('your_app', model_name)
        except LookupError:
            logger.error(f"Modèle {model_name} introuvable")
            return results
        
        # Récupérer les modifications depuis le serveur
        last_sync = self.config.last_sync_download or timezone.now() - timedelta(days=365)
        
        url = f"{self.config.remote_api_url}/sync/{model_name.lower()}/"
        params = {
            'hospital_id': self.hospital_id,
            'updated_since': last_sync.isoformat(),
            'is_shared': True
        }
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            remote_objects = response.json()
            
            for remote_data in remote_objects:
                try:
                    result = self._download_object(remote_data, Model, model_name)
                    results[result] += 1
                except Exception as e:
                    logger.error(f"Erreur download {model_name}: {e}")
                    results['failed'] += 1
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur HTTP download {model_name}: {e}")
            results['failed'] += 1
        
        return results
    
    @transaction.atomic
    def _download_object(self, remote_data, Model, model_name):
        """Télécharger et appliquer un objet distant"""
        
        # Identifier l'objet local
        code = remote_data.get('code')
        if not code:
            logger.error(f"Objet sans code: {remote_data}")
            return 'failed'
        
        try:
            local_obj = Model.objects.get(code=code, hospital_id=self.hospital_id)
            operation = 'UPDATE'
        except Model.DoesNotExist:
            local_obj = None
            operation = 'CREATE'
        
        # Créer un log
        sync_log = SyncLog.objects.create(
            hospital_id=self.hospital_id,
            direction='DOWNLOAD',
            status='PENDING',
            content_type=ContentType.objects.get_for_model(Model),
            object_id=local_obj.id if local_obj else 0,
            operation=operation,
            data_snapshot=remote_data,
            remote_updated_at=datetime.fromisoformat(remote_data.get('updatedAt')),
            local_updated_at=local_obj.updatedAt if local_obj else timezone.now()
        )
        
        try:
            # Vérifier les conflits
            if local_obj and operation == 'UPDATE':
                remote_updated = datetime.fromisoformat(remote_data.get('updatedAt'))
                local_updated = local_obj.updatedAt
                
                if local_updated > remote_updated:
                    # Conflit: la version locale est plus récente
                    sync_log.status = 'CONFLICT'
                    sync_log.error_message = 'Version locale plus récente'
                    sync_log.save()
                    
                    if self.config.conflict_strategy == 'LOCAL_WINS':
                        return 'skipped'
                    elif self.config.conflict_strategy == 'REMOTE_WINS':
                        pass  # Continuer l'import
                    else:
                        return 'conflict'
            
            # Appliquer les données
            if operation == 'CREATE':
                # Nettoyer les données pour création
                clean_data = self._clean_data_for_create(remote_data)
                local_obj = Model.objects.create(**clean_data)
            else:
                # Mise à jour
                clean_data = self._clean_data_for_update(remote_data)
                for key, value in clean_data.items():
                    setattr(local_obj, key, value)
                local_obj.save()
            
            sync_log.status = 'SUCCESS'
            sync_log.synced_at = timezone.now()
            sync_log.object_id = local_obj.id
            sync_log.save()
            
            return 'success'
            
        except Exception as e:
            sync_log.status = 'FAILED'
            sync_log.error_message = str(e)
            sync_log.save()
            return 'failed'
    
    # ==================== UTILITAIRES ====================
    
    def _serialize_object(self, obj):
        """Sérialiser un objet Django en JSON"""
        from django.forms.models import model_to_dict
        
        data = model_to_dict(obj)
        
        # Convertir les dates en ISO format
        for key, value in data.items():
            if isinstance(value, (datetime, timezone.datetime)):
                data[key] = value.isoformat()
        
        return data
    
    def _clean_data_for_create(self, data):
        """Nettoyer les données pour création"""
        excluded_fields = ['id', 'createdAt', 'updatedAt', 'timeAt']
        return {k: v for k, v in data.items() if k not in excluded_fields}
    
    def _clean_data_for_update(self, data):
        """Nettoyer les données pour mise à jour"""
        excluded_fields = ['id', 'code', 'createdAt', 'updatedAt', 'timeAt', 'hospital_id']
        return {k: v for k, v in data.items() if k not in excluded_fields}
    
    def _resolve_conflict(self, sync_log, remote_data):
        """Résoudre automatiquement un conflit"""
        if self.config.conflict_strategy == 'REMOTE_WINS':
            # Appliquer les données distantes
            self._apply_remote_data(sync_log, remote_data)
        elif self.config.conflict_strategy == 'LOCAL_WINS':
            # Renvoyer les données locales
            self._resend_local_data(sync_log)
    
    def get_sync_status(self):
        """Obtenir le statut de synchronisation"""
        return {
            'last_upload': self.config.last_sync_upload,
            'last_download': self.config.last_sync_download,
            'pending_uploads': SyncLog.objects.filter(
                hospital_id=self.hospital_id,
                direction='UPLOAD',
                status='PENDING'
            ).count(),
            'pending_downloads': SyncLog.objects.filter(
                hospital_id=self.hospital_id,
                direction='DOWNLOAD',
                status='PENDING'
            ).count(),
            'conflicts': SyncLog.objects.filter(
                hospital_id=self.hospital_id,
                status='CONFLICT'
            ).count(),
        }