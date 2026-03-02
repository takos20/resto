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
        self.session = requests.Session()

    def download_changes(self, force=False):
        """
        Télécharger les modifications du serveur distant
        """

        if not self.config.is_active:
            logger.warning(f"Sync désactivée pour hospital {self.hospital_id}")
            return None

        if not self.config.auto_sync and not force:
            logger.info("Auto-sync désactivé")
            return None

        results = {
            'success': 0,
            'failed': 0,
            'conflicts': 0,
            'skipped': 0
        }

        global_success = True

        try:
            for model_name in self.config.models_to_sync:
                try:
                    model_results = self._download_model(model_name)

                    for key in results.keys():
                        results[key] += model_results.get(key, 0)

                except Exception as e:
                    logger.exception(f"Erreur download model {model_name}: {e}")
                    results['failed'] += 1
                    global_success = False

            # ✅ On met à jour le timestamp seulement si pas d’erreur critique
            if global_success:
                self.config.last_sync_download = timezone.now()
                self.config.save(update_fields=['last_sync_download'])

            logger.info(f"Download terminé pour hospital {self.hospital_id}: {results}")

            return results

        except Exception as e:
            logger.exception(f"Erreur globale download_changes: {e}")
            raise


    def _download_model(self, model_path):
        """
        Télécharger les changements d'un modèle spécifique
        """

        results = {
            'success': 0,
            'failed': 0,
            'conflicts': 0,
            'skipped': 0
        }

        try:
            app_label, model_name = model_path.split(".")
            Model = apps.get_model(app_label, model_name)
        except LookupError:
            logger.error(f"Modèle {model_name} introuvable")
            return results

        last_sync = self.config.last_sync_download or (
            timezone.now() - timedelta(days=365)
        )

        url = f"{self.config.remote_api_url}/sync/{model_name.lower()}"

        params = {
            'hospital_id': self.hospital_id,
            'updated_since': last_sync.isoformat(),
            'is_shared': False
        }

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            remote_objects = response.json()

            logger.info(
                f"{len(remote_objects)} objets reçus pour {model_name}"
            )

            for remote_data in remote_objects:
                try:
                    result = self._download_object(
                        remote_data,
                        Model
                    )
                    results[result] += 1

                except Exception as e:
                    logger.exception(
                        f"Erreur traitement objet {model_name}: {e}"
                    )
                    results['failed'] += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur HTTP download {model_name}: {e}")
            results['failed'] += 1

        return results


    @transaction.atomic
    def _download_object(self, remote_data, Model):
        """
        Synchroniser un objet individuel
        Retourne: success | failed | conflicts | skipped
        """

        remote_id = remote_data.get("id")

        if not remote_id:
            return "failed"

        try:
            local_obj = Model.objects.filter(id=remote_id).first()

            remote_updated_at = remote_data.get("updated_at")
            remote_deleted = remote_data.get("is_deleted", False)

            # -----------------------------
            # 1️⃣ Objet inexistant localement
            # -----------------------------
            if not local_obj:

                if remote_deleted:
                    return "skipped"

                Model.objects.create(**remote_data)
                return "success"

            # -----------------------------
            # 2️⃣ Gestion Soft Delete
            # -----------------------------
            if remote_deleted:
                local_obj.delete()
                return "success"

            # -----------------------------
            # 3️⃣ Gestion Conflit
            # -----------------------------
            local_updated_at = local_obj.updated_at.isoformat()

            if remote_updated_at < local_updated_at:
                logger.warning(
                    f"Conflit détecté ID {remote_id}"
                )
                return "conflicts"

            # -----------------------------
            # 4️⃣ Mise à jour normale
            # -----------------------------
            for field, value in remote_data.items():
                if field in [f.name for f in Model._meta.fields]:
                    setattr(local_obj, field, value)

            local_obj.save()
            return "success"

        except Exception as e:
            logger.exception(f"Erreur sync objet ID {remote_id}: {e}")
            return "failed"