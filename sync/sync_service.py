# sync/services/sync_service.py
import requests
import logging
from django.db import transaction
from django.apps import apps
from django.utils import timezone
from datetime import datetime, timedelta
from .models import SyncLog, SyncConfig

logger = logging.getLogger(__name__)
from django.contrib.contenttypes.models import ContentType

class SyncService:
    def __init__(self, hospital_id, config):
        self.hospital_id = hospital_id
        self.config = config
        self.session = self._create_session()

    def _create_session(self):
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json"
        })
        return session

    # ================= UPLOAD (Local → Remote) =================
    def upload_changes(self, force=False):
        if not self.config.is_active:
            return {'skipped': 0, 'failed': 0, 'success': 0, 'conflicts': 0}

        if not self.config.auto_sync and not force:
            return {'skipped': 0, 'failed': 0, 'success': 0, 'conflicts': 0}

        results = {'success': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}

        for model_name in self.config.models_to_sync:
            try:
                model_results = self._upload_model(model_name)
                for k in results:
                    results[k] += model_results.get(k, 0)
            except Exception:
                results['failed'] += 1

        self.config.last_sync_upload = timezone.now()
        self.config.save()
        return results

    def _upload_model(self, model_name):
        results = {'success': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}

        app_label, model = model_name.split(".")
        Model = apps.get_model(app_label, model)

        last_sync = self.config.last_sync_upload or timezone.now() - timedelta(days=365)

        queryset = Model.objects.filter(
            hospital_id=self.hospital_id,
            updatedAt__gt=last_sync,
            deleted=False
        )

        if hasattr(Model, 'is_shared'):
            queryset = queryset.filter(is_shared=True)

        for obj in queryset:
            try:
                result = self._upload_object(obj, model_name)
                results[result] += 1
            except Exception:
                results['failed'] += 1

        return results

    def _upload_object(self, obj, model_name):
        url = f"{self.config.remote_api_url}/sync/{model_name.lower()}/"
        data = self._serialize_object(obj)
        data['hospital_id'] = self.hospital_id

        response = self.session.post(url, json=data)

        if response.status_code in [200, 201]:
            return 'success'
        if response.status_code == 409:
            return 'conflicts'
        return 'failed'

    # ================= DOWNLOAD (Remote → Local) =================
    def download_changes(self, force=False):
        if not self.config.is_active:
            return {'skipped': 0, 'failed': 0, 'success': 0, 'conflicts': 0}

        results = {'success': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}

        for model_name in self.config.models_to_sync:
            try:
                model_results = self._download_model(model_name)
                for k in results:
                    results[k] += model_results.get(k, 0)
            except Exception:
                results['failed'] += 1

        self.config.last_sync_download = timezone.now()
        self.config.save()
        return results

    def _download_model(self, model_name):
        results = {'success': 0, 'failed': 0, 'conflicts': 0, 'skipped': 0}

        app_label, model = model_name.split(".")
        Model = apps.get_model(app_label, model)

        last_sync = self.config.last_sync_download or timezone.now() - timedelta(days=365)

        url = f"{self.config.remote_api_url}/sync/{model_name.lower()}/"
        params = {
            'hospital_id': self.hospital_id,
            'updated_since': last_sync.isoformat(),
            'is_shared': True
        }

        response = self.session.get(url, params=params)
        if response.status_code != 200:
            results['failed'] += 1
            return results

        for remote in response.json():
            try:
                self._download_object(remote, Model)
                results['success'] += 1
            except Exception:
                results['failed'] += 1

        return results

    @transaction.atomic
    def _download_object(self, remote_data, Model):
        code = remote_data.get('code')
        if not code:
            return

        obj, created = Model.objects.get_or_create(
            code=code,
            hospital_id=self.hospital_id,
            defaults=self._clean_data_for_create(remote_data)
        )

        if not created:
            for k, v in self._clean_data_for_update(remote_data).items():
                setattr(obj, k, v)
            obj.save()

    # ================= UTILITIES =================
    def _serialize_object(self, obj):
        from django.forms.models import model_to_dict
        data = model_to_dict(obj)

        for k, v in data.items():
            if isinstance(v, (datetime, timezone.datetime)):
                data[k] = v.isoformat()

        return data

    def _clean_data_for_create(self, data):
        return {k: v for k, v in data.items() if k not in ['id', 'createdAt', 'updatedAt']}

    def _clean_data_for_update(self, data):
        return {k: v for k, v in data.items() if k not in ['id', 'code', 'hospital_id']}

    def get_sync_status(self):
        return {
            'last_upload': self.config.last_sync_upload,
            'last_download': self.config.last_sync_download,
            'pending_uploads': SyncLog.objects.filter(direction='UPLOAD', status='PENDING').count(),
            'pending_downloads': SyncLog.objects.filter(direction='DOWNLOAD', status='PENDING').count(),
        }