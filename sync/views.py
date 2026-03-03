# sync/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from globals.pagination import CustomPagination
from hospital.helpers import SyncPermission
from sync.filters import SyncConfigFilter, SyncLogFilter
from sync.models import SyncConfig, SyncLog
from .sync_service import SyncService
from .serializers import SyncLogSerializer, SyncConfigSerializer
from rest_framework.permissions import AllowAny, IsAuthenticated, DjangoModelPermissions
from rest_framework.renderers import JSONRenderer
from django_filters import rest_framework as filters
from django.apps import apps
from rest_framework.response import Response
from django.utils.dateparse import parse_datetime
from django.core.paginator import Paginator
class SyncViewSet(viewsets.ViewSet):
    authentication_classes = []
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend]

    def get_permissions(self):
        return [AllowAny()]


    @action(detail=False, methods=["get"], url_path=r'(?P<model>[^/.]+)')
    def sync_model(self, request, model=None):

        hospital_id = request.query_params.get("hospital_id")
        updated_since = request.query_params.get("updated_since")
        page_number = request.query_params.get("page", 1)
        limit = int(request.query_params.get("limit", 500))

        api_key = request.headers.get("X-API-KEY")

        if not hospital_id:
            return Response({"error": "hospital_id requis"}, status=400)

        try:
            config = SyncConfig.objects.get(hospital_id=hospital_id)

            # 🔐 Vérification API KEY
            if not api_key or api_key != config.api_token:
                return Response({"error": "Unauthorized"}, status=401)

            model_name = model.capitalize()

            model_path = None
            for m in config.models_to_sync:
                if m.endswith(f".{model_name}"):
                    model_path = m
                    break

            if not model_path:
                return Response({"error": "Model non autorisé"}, status=404)

            app_label, model_cls = model_path.split(".")
            Model = apps.get_model(app_label, model_cls)

        except SyncConfig.DoesNotExist:
            return Response({"error": "SyncConfig introuvable"}, status=404)

        # =========================
        # FILTRAGE
        # =========================

        queryset = Model.objects.filter(hospital_id=hospital_id)

        if updated_since:
            parsed_date = parse_datetime(updated_since)
            if parsed_date:
                queryset = queryset.filter(updatedAt__gt=parsed_date)

        queryset = queryset.order_by("updatedAt")

        # =========================
        # PAGINATION
        # =========================

        paginator = Paginator(queryset, limit)
        page = paginator.get_page(page_number)

        data = list(page.object_list.values())

        return Response({
            "count": paginator.count,
            "total_pages": paginator.num_pages,
            "current_page": page.number,
            "has_next": page.has_next(),
            "has_previous": page.has_previous(),
            "results": data
        })
    @action(detail=False, methods=['post'], url_path='upload')
    def upload(self, request):
        hospital_id = request.data.get('hospital_id')
        force = request.data.get('force', False)

        if not hospital_id:
            return Response({'error': 'hospital_id requis'}, status=400)

        try:
            config = SyncConfig.objects.get(hospital_id=hospital_id)
            service = SyncService(hospital_id=hospital_id, config=config)
            results = service.upload_changes(force=force)

            return Response({'message': 'Upload terminé', 'results': results})

        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'], url_path='download')
    def download(self, request):
        hospital_id = request.data.get('hospital_id')
        force = request.data.get('force', False)

        if not hospital_id:
            return Response({'error': 'hospital_id requis'}, status=400)

        try:
            config = SyncConfig.objects.get(hospital_id=hospital_id)
            service = SyncService(hospital_id=hospital_id, config=config)
            results = service.download_changes(force=force)

            return Response({'message': 'Download terminé', 'results': results})

        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'], url_path='full_sync')
    def full_sync(self, request):
        hospital_id = request.data.get('hospital_id')

        if not hospital_id:
            return Response({'error': 'hospital_id requis'}, status=400)

        try:
            config = SyncConfig.objects.get(hospital_id=hospital_id)
            service = SyncService(hospital_id=hospital_id, config=config)

            upload_results = service.upload_changes(force=True)
            download_results = service.download_changes(force=True)

            return Response({
                'message': 'Sync complète terminée',
                'upload': upload_results,
                'download': download_results,
                'status': service.get_sync_status()
            })

        except Exception as e:
            return Response({'error': str(e)}, status=500)
class SyncLogViewSet(viewsets.ViewSet):
    queryset = SyncLog.objects.all()
    serializer_class = SyncLogSerializer
    renderer_classes = [JSONRenderer]
    permission_classes = (IsAuthenticated, DjangoModelPermissions)
    pagination_class = CustomPagination
    filterset_class = SyncLogFilter
    filter_backends = (filters.DjangoFilterBackend,)